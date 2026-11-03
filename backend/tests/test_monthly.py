from datetime import date

from app.models import Allocation, Assignment, Person, Project, WeekReview
from tests.conftest import make_milestone


def _person(db, name="傅相杰", monthly=30.0):
    p = Person(name=name, monthly_capacity=monthly, edited_in_app=True)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _project(db, name):
    proj = Project(name=name, state="active", edited_in_app=True)
    db.add(proj)
    db.commit()
    db.refresh(proj)
    return proj


def _alloc(db, person, project, week, days, milestone_id=None):
    a = Allocation(
        person_id=person.id,
        project_id=project.id,
        week=date.fromisoformat(week),
        days=days,
        milestone_id=milestone_id,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _review(db, person, week, reviewed=True):
    db.add(WeekReview(person_id=person.id, week=date.fromisoformat(week), reviewed=reviewed))
    db.commit()


def test_person_month_weeks_and_occupancy(client, db):
    p = _person(db)
    proj = _project(db, "贵州矿产预测")
    _alloc(db, p, proj, "2026-11-02", 10)
    _alloc(db, p, proj, "2026-11-02", 0.5)
    _alloc(db, p, proj, "2026-11-09", 5)
    # 上一个月的分配不计入本月
    _alloc(db, p, proj, "2026-10-26", 8)

    r = client.get(f"/api/persons/{p.id}/month", params={"month": "2026-11"})
    assert r.status_code == 200
    body = r.json()
    # MonthPersonDetail.weeks 是 list[MonthWeekOut]（对象），不是字符串列表；
    # 字符串列表的是 MonthRosterOut.weeks（见 Task 3）。
    assert [w["week"] for w in body["weeks"]] == [
        "2026-11-02", "2026-11-09", "2026-11-16", "2026-11-23", "2026-11-30",
    ]
    assert body["used_days"] == 15.5
    assert body["over_days"] is None
    # 本月有分配的周还没核对 → 不给精确剩余
    assert body["remaining_days"] is None
    assert body["reviewed"] is False


def test_person_month_cross_month_week_belongs_to_november(client, db):
    p = _person(db)
    proj = _project(db, "贵州矿产预测")
    # 周一 2026-11-30，week_end 是 12-06 —— 整周算进 11 月
    _alloc(db, p, proj, "2026-11-30", 4)
    _alloc(db, p, proj, "2026-10-26", 99)  # 10 月的周，不算

    body = client.get(f"/api/persons/{p.id}/month", params={"month": "2026-11"}).json()
    assert body["used_days"] == 4
    # MonthWeekOut 是对象；下一行断言 week 键，再下一行取整条对象
    assert body["weeks"][-1]["week"] == "2026-11-30"
    detail = body["weeks"][-1]
    assert detail["total_days"] == 4
    assert detail["week_end"] == "2026-12-06"


def test_person_month_over_days(client, db):
    p = _person(db, monthly=20.0)
    proj = _project(db, "贵州矿产预测")
    _alloc(db, p, proj, "2026-11-02", 18.5)
    _review(db, p, "2026-11-02")

    body = client.get(f"/api/persons/{p.id}/month", params={"month": "2026-11"}).json()
    assert body["used_days"] == 18.5
    assert body["over_days"] is None
    assert body["remaining_days"] == 1.5
    assert body["reviewed"] is True


def test_person_month_over_days_when_exceeded(client, db):
    p = _person(db, monthly=10.0)
    proj = _project(db, "贵州矿产预测")
    _alloc(db, p, proj, "2026-11-02", 12.5)
    _review(db, p, "2026-11-02")

    body = client.get(f"/api/persons/{p.id}/month", params={"month": "2026-11"}).json()
    assert body["over_days"] == 2.5
    # 超额时剩余为负值也照给（口径：剩余 = capacity - used）
    assert body["remaining_days"] == -2.5


def test_person_month_remaining_blocked_by_unreviewed_alloc_week(client, db):
    p = _person(db, monthly=20.0)
    proj = _project(db, "贵州矿产预测")
    _alloc(db, p, proj, "2026-11-02", 5)
    _alloc(db, p, proj, "2026-11-09", 7)
    _review(db, p, "2026-11-02")          # 只有一周核对过

    body = client.get(f"/api/persons/{p.id}/month", params={"month": "2026-11"}).json()
    assert body["reviewed"] is False
    assert body["remaining_days"] is None


def test_person_month_empty_weeks_do_not_block_reviewed(client, db):
    p = _person(db, monthly=20.0)
    proj = _project(db, "贵州矿产预测")
    _alloc(db, p, proj, "2026-11-02", 5)
    _review(db, p, "2026-11-02")
    # 本月其余周都是空周，且没核对 —— 不参与判定

    body = client.get(f"/api/persons/{p.id}/month", params={"month": "2026-11"}).json()
    assert body["reviewed"] is True
    assert body["remaining_days"] == 15.0


def test_person_month_zero_allocation_is_fully_remaining(client, db):
    p = _person(db, monthly=30.0)

    body = client.get(f"/api/persons/{p.id}/month", params={"month": "2026-11"}).json()
    assert body["used_days"] == 0
    assert body["reviewed"] is True
    assert body["remaining_days"] == 30.0
    assert body["projects"] == []


def test_person_month_adding_alloc_to_reviewed_week_reverts_review(client, db):
    p = _person(db, monthly=30.0)
    proj = _project(db, "贵州矿产预测")
    mile = make_milestone(db, proj, "节点一")
    _alloc(db, p, proj, "2026-11-02", 5)
    _review(db, p, "2026-11-02")
    assert client.get(f"/api/persons/{p.id}/month", params={"month": "2026-11"}).json()["reviewed"] is True

    # 往一个空周加分配 → 该周未核对 → 整月退回「待核对」
    r = client.post(
        "/api/allocations",
        json={"person_id": p.id, "project_id": proj.id, "week": "2026-11-16",
              "days": 2, "milestone_id": mile.id},
    )
    assert r.status_code == 201
    body = client.get(f"/api/persons/{p.id}/month", params={"month": "2026-11"}).json()
    assert body["reviewed"] is False
    assert body["remaining_days"] is None
    assert body["used_days"] == 7


def test_person_month_projects_merge_allocation_and_assignment(client, db):
    p = _person(db)
    p1 = _project(db, "贵州矿产预测")
    p2 = _project(db, "北京仓储")
    _alloc(db, p, p1, "2026-11-02", 10)
    db.add(Assignment(person_id=p.id, project_id=p2.id, role="项目负责人"))
    db.add(Assignment(person_id=p.id, project_id=p2.id, role="业务对接"))
    db.commit()

    body = client.get(f"/api/persons/{p.id}/month", params={"month": "2026-11"}).json()
    by_id = {row["project_id"]: row for row in body["projects"]}
    assert by_id[p1.id] == {
        "project_id": p1.id, "project_name": "贵州矿产预测", "roles": [],
        "days": 10.0, "has_allocation": True, "has_assignment": False,
    }
    assert by_id[p2.id] == {
        "project_id": p2.id, "project_name": "北京仓储",
        "roles": ["项目负责人", "业务对接"],
        "days": 0.0, "has_allocation": False, "has_assignment": True,
    }


def test_person_month_invalid_month_returns_400(client, db):
    p = _person(db)
    for bad in ("2026-13", "2026-1", "abc", ""):
        assert client.get(f"/api/persons/{p.id}/month", params={"month": bad}).status_code == 400
