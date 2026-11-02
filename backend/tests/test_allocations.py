"""E2 public-contract tests: real SQLite/API, no fabricated capacity or effort."""
import pytest

WEEK = '2026-11-02'


def setup(client):
    person = client.post('/api/persons', json={'name': '傅相杰', 'skills': '地质AI', 'weekly_capacity': 5}).json()
    a = client.post('/api/projects', json={'name': '贵州V1.5'}).json()
    b = client.post('/api/projects', json={'name': '卡鉴', 'state': 'maintenance'}).json()
    return person['id'], a['id'], b['id']


def allocate(client, person, project, days, week=WEEK, **kwargs):
    r = client.post('/api/allocations', json=dict(person_id=person, project_id=project, week=week, days=days, **kwargs))
    assert r.status_code == 201, r.text
    return r.json()


def summary(client, person, week=WEEK):
    r = client.get(f'/api/persons/{person}/weeks/{week}')
    assert r.status_code == 200, r.text
    return r.json()


def test_assignment_does_not_invent_allocation(client):
    p, a, _ = setup(client)
    r = client.post('/api/assignments', json={'person_id': p, 'project_id': a, 'role': '项目负责人'})
    assert r.status_code == 201
    m = client.post(f'/api/projects/{a}/milestones', json={'name': '交付', 'assignee_id': p})
    assert m.status_code == 201
    s = summary(client, p)
    assert s['allocations'] == [] and s['total_days'] == 0
    assert s['remaining_days'] is None and s['reviewed'] is False
    assert len(s['unallocated_milestones']) == 1
    assert len(s['assignments']) == 1


def test_conflict_full_sources_and_stable_id(client):
    p, a, b = setup(client)
    x = allocate(client, p, a, 3)
    y = allocate(client, p, b, 2.5)
    s = summary(client, p)
    assert (s['total_days'], s['over_days'], s['remaining_days']) == (5.5, .5, None)
    assert {row['id'] for row in s['allocations']} == {x['id'], y['id']}
    assert client.get(f'/api/allocations?project_id={a}&week={WEEK}').json()[0]['id'] == x['id']
    r = client.patch(f"/api/allocations/{y['id']}", json={'days': 1})
    assert r.status_code == 200 and r.json()['id'] == y['id']
    assert summary(client, p)['remaining_days'] is None
    assert client.put(f'/api/persons/{p}/weeks/{WEEK}/review', json={'reviewed': True}).status_code == 200
    assert summary(client, p)['remaining_days'] == 1
    client.patch(f"/api/allocations/{x['id']}", json={'days': 2.5})
    assert summary(client, p)['reviewed'] is False
    assert client.delete(f"/api/allocations/{y['id']}").status_code == 200
    assert summary(client, p)['total_days'] == 2.5


def test_capacity_unknown_zero_override_delete(client):
    p, a, _ = setup(client)
    allocate(client, p, a, 3)
    path = f'/api/persons/{p}/weeks/{WEEK}/capacity'
    assert client.put(path, json={'days': 0}).status_code == 200
    assert summary(client, p)['capacity'] == 0
    client.put(path, json={'days': None})
    s = summary(client, p)
    assert s['capacity'] is None and s['capacity_source'] == 'override'
    assert s['remaining_days'] is None and s['over_days'] is None
    assert client.delete(path).status_code == 200
    assert summary(client, p)['capacity'] == 5
    client.patch(f'/api/persons/{p}', json={'weekly_capacity': None})
    assert summary(client, p)['capacity'] is None


@pytest.mark.parametrize('bad', [-.5, 1.2, True, 'NaN'])
def test_invalid_days_preserve_values(client, bad):
    p, a, _ = setup(client)
    x = allocate(client, p, a, 3)
    client.put(f'/api/persons/{p}/weeks/{WEEK}/review', json={'reviewed': True})
    assert client.patch(f"/api/allocations/{x['id']}", json={'days': bad}).status_code == 422
    assert client.patch(f'/api/persons/{p}', json={'weekly_capacity': bad}).status_code == 422
    assert client.put(f'/api/persons/{p}/weeks/{WEEK}/capacity', json={'days': bad}).status_code == 422
    s = summary(client, p)
    assert s['total_days'] == 3 and s['capacity'] == 5 and s['reviewed'] is True


def test_week_and_reference_validation(client):
    p, a, b = setup(client)
    m = client.post(f'/api/projects/{a}/milestones', json={'name': '节点'}).json()
    payload = dict(person_id=p, project_id=b, milestone_id=m['id'], week=WEEK, days=1)
    assert client.post('/api/allocations', json=payload).status_code == 422
    payload.update(project_id=a, week='2026-11-03')
    assert client.post('/api/allocations', json=payload).status_code == 422
    payload.update(week='2026-12-28')
    assert client.post('/api/allocations', json=payload).status_code == 201
    assert summary(client, p, '2026-12-28')['week_end'] == '2027-01-03'
    assert summary(client, p)['allocations'] == []


def test_move_invalidates_both_person_week_reviews(client):
    p, a, _ = setup(client)
    q = client.post('/api/persons', json={'name': '另一人'}).json()['id']
    x = allocate(client, p, a, 1)
    for who, week in [(p, WEEK), (q, '2026-11-09')]:
        client.put(f'/api/persons/{who}/weeks/{week}/review', json={'reviewed': True})
    assert client.patch(f"/api/allocations/{x['id']}", json={'person_id': q, 'week': '2026-11-09'}).status_code == 200
    assert summary(client, p)['reviewed'] is False
    assert summary(client, q, '2026-11-09')['reviewed'] is False


def test_delete_protected_by_references(client):
    p, a, _ = setup(client)
    m = client.post(f'/api/projects/{a}/milestones', json={'name': '节点'}).json()
    allocate(client, p, a, 1, milestone_id=m['id'])
    assert client.delete(f"/api/milestones/{m['id']}").status_code == 409
    assert client.delete(f'/api/projects/{a}').status_code == 409
    c = client.post('/api/projects', json={'name': '空项目'}).json()['id']
    asg = client.post('/api/assignments', json={'person_id': p, 'project_id': c, 'role': '业务对接'}).json()
    assert client.delete(f'/api/projects/{c}').status_code == 409
    assert client.delete(f"/api/allocations/{client.get('/api/allocations').json()[0]['id']}").status_code == 200
    assert client.delete(f"/api/assignments/{asg['id']}").status_code == 200
    assert client.delete(f'/api/projects/{c}').status_code == 200


def test_person_update_and_assignment_crud(client):
    p, a, _ = setup(client)
    assert client.get('/api/persons').json()[0]['skills'] == '地质AI'
    q = client.post('/api/persons', json={'name': '另一人'}).json()['id']
    assert client.patch(f'/api/persons/{q}', json={'name': '傅相杰'}).status_code == 409
    assert client.patch(f'/api/persons/{p}', json={'name': None}).status_code == 422
    r = client.post('/api/assignments', json={'person_id': p, 'project_id': a, 'role': '统筹管理'})
    assert r.status_code == 201
    aid = r.json()['id']
    assert client.patch(f'/api/assignments/{aid}', json={'role': '业务对接'}).status_code == 200
    assert client.get(f'/api/assignments?project_id={a}').json()[0]['role'] == '业务对接'
    assert client.delete(f'/api/assignments/{aid}').status_code == 200
    assert client.get(f'/api/assignments?person_id={p}').json() == []
    assert client.post(f'/api/persons/{p}/archive').status_code == 200
    assert p not in [row['id'] for row in client.get('/api/persons').json()]
    assert client.post(f'/api/persons/{p}/restore').status_code == 200


def test_project_view_and_person_view_agree_without_double_counting(client):
    """项目页与人员页共用同一份 Allocation：同一稳定 ID、同一占用合计，不重复计入。"""
    p, a, b = setup(client)
    x = allocate(client, p, a, 3)
    y = allocate(client, p, b, 2.5)
    s = summary(client, p)
    # 项目筛选只影响视图，不掩盖该人的完整冲突集合
    assert {row['id'] for row in s['allocations']} == {x['id'], y['id']}
    assert s['total_days'] == 5.5
    project_rows = client.get(f'/api/allocations?project_id={a}&week={WEEK}').json()
    assert [row['id'] for row in project_rows] == [x['id']]
    assert project_rows[0]['days'] == 3
    # 人员页与项目页引用同一批 Allocation，不会把 3 记成 3+2.5
    assert sum(row['days'] for row in s['allocations']) == 5.5
