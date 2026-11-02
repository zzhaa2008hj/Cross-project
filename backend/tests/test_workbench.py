"""E3 工作台：跨周逾期、临近交付周区间、维护单列、完整冲突来源与空态判定。

固定 today = 2026-11-02（周一），避免测试随真实日期漂移。
"""
from datetime import date

import pytest

TODAY = date(2026, 11, 2)
WEEK = "2026-11-02"
NEXT_WEEK = "2026-11-09"
FAR_WEEK = "2026-11-16"


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    from app.services import workbench as workbench_service

    monkeypatch.setattr(workbench_service, "today_shanghai", lambda: TODAY)


def person(client, name, capacity=5.0):
    return client.post(
        "/api/persons", json={"name": name, "weekly_capacity": capacity}
    ).json()


def project(client, name, state="active", priority=""):
    return client.post(
        "/api/projects", json={"name": name, "state": state, "priority": priority}
    ).json()


def milestone(
    client,
    project_id,
    name,
    commit_date=None,
    state="未开始",
    assignee_id=None,
    start_date=None,
):
    return client.post(
        f"/api/projects/{project_id}/milestones",
        json={
            "name": name,
            "commit_date": commit_date,
            "start_date": start_date,
            "state": state,
            "assignee_id": assignee_id,
        },
    ).json()


def assign(client, person_id, project_id, role="项目负责人"):
    return client.post(
        "/api/assignments",
        json={"person_id": person_id, "project_id": project_id, "role": role},
    ).json()


def allocate(client, person_id, project_id, days, week=WEEK, milestone_id=None):
    return client.post(
        "/api/allocations",
        json={
            "person_id": person_id,
            "project_id": project_id,
            "week": week,
            "days": days,
            "milestone_id": milestone_id,
        },
    ).json()


def board(client, **params):
    r = client.get("/api/workbench", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def kinds(data):
    return [item["kind"] for item in data["todos"]]


# ---------------------------------------------------------------- 逾期跨周


def test_overdue_not_hidden_by_week_switch(client):
    p = person(client, "傅相杰")
    pr = project(client, "贵州V1.5")
    ms = milestone(client, pr["id"], "V1.5交付", commit_date="2026-10-20", state="进行中")
    assign(client, p["id"], pr["id"])
    allocate(client, p["id"], pr["id"], 3, milestone_id=ms["id"])

    first = board(client, week=WEEK)
    assert "overdue" in kinds(first)
    overdue = [t for t in first["todos"] if t["kind"] == "overdue"]
    assert overdue[0]["milestone_id"] == ms["id"]
    assert overdue[0]["due_date"] == "2026-10-20"

    # 切到下一周、再切到更远的周：逾期仍然在
    for week in (NEXT_WEEK, FAR_WEEK):
        later = board(client, week=week)
        assert "overdue" in kinds(later), week
        assert any(
            t["milestone_id"] == ms["id"] for t in later["todos"] if t["kind"] == "overdue"
        )


def test_terminal_milestones_are_not_overdue(client):
    p = person(client, "傅相杰")
    pr = project(client, "贵州V1.5")
    for state in ("已完成", "已取消"):
        milestone(client, pr["id"], f"节点{state}", commit_date="2026-10-20", state=state)
    assign(client, p["id"], pr["id"])
    data = board(client, week=WEEK)
    assert "overdue" not in kinds(data)


# ---------------------------------------------------------------- 临近交付


def test_due_soon_labeled_with_week_range(client):
    p = person(client, "傅相杰")
    pr = project(client, "贵州V1.5")
    inside = milestone(
        client, pr["id"], "本周到期", commit_date="2026-11-05", state="进行中"
    )
    outside = milestone(
        client, pr["id"], "下周到期", commit_date="2026-11-12", state="进行中"
    )
    assign(client, p["id"], pr["id"])

    data = board(client, week=WEEK)
    due = [t for t in data["todos"] if t["kind"] == "due_soon"]
    assert [t["milestone_id"] for t in due] == [inside["id"]]
    assert due[0]["week_label"] == "2026-11-02 ~ 2026-11-08"

    nxt = board(client, week=NEXT_WEEK)
    due_next = [t for t in nxt["todos"] if t["kind"] == "due_soon"]
    assert [t["milestone_id"] for t in due_next] == [outside["id"]]
    assert due_next[0]["week_label"] == "2026-11-09 ~ 2026-11-15"


# ---------------------------------------------------------------- 维护单列


def test_maintenance_project_separate_but_occupancy_counts(client):
    p = person(client, "傅相杰")
    active = project(client, "贵州V1.5", priority="P1")
    maint = project(client, "卡鉴", state="maintenance")
    assign(client, p["id"], active["id"])
    assign(client, p["id"], maint["id"], role="节点执行")
    allocate(client, p["id"], active["id"], 3)
    allocate(client, p["id"], maint["id"], 2.5)

    data = board(client, week=WEEK)
    assert [row["id"] for row in data["projects"]] == [active["id"]]
    assert [row["id"] for row in data["maintenance_projects"]] == [maint["id"]]

    card = data["people"][0]
    assert card["total_days"] == 5.5
    assert card["over_days"] == 0.5
    assert {a["project_id"] for a in card["allocations"]} == {active["id"], maint["id"]}


# ---------------------------------------------------------------- 负责人过滤


def test_owner_filter_keeps_complete_person_conflict(client):
    owner = person(client, "赵辉辉")
    worker = person(client, "傅相杰")
    a = project(client, "贵州V1.5")
    b = project(client, "卡鉴")
    assign(client, owner["id"], a["id"], role="项目负责人")
    assign(client, worker["id"], a["id"], role="节点执行")
    assign(client, worker["id"], b["id"], role="节点执行")
    allocate(client, worker["id"], a["id"], 3)
    allocate(client, worker["id"], b["id"], 2.5)

    data = board(client, week=WEEK, owner_person_id=owner["id"])
    assert [row["id"] for row in data["projects"]] == [a["id"]]
    card = [c for c in data["people"] if c["person_id"] == worker["id"]][0]
    # 过滤只决定项目与人员范围，不裁剪这个人的冲突来源
    assert card["total_days"] == 5.5
    assert card["over_days"] == 0.5
    assert {a_["project_id"] for a_ in card["allocations"]} == {a["id"], b["id"]}


def test_project_filter_scopes_projects(client):
    p = person(client, "傅相杰")
    a = project(client, "贵州V1.5")
    b = project(client, "卡鉴")
    assign(client, p["id"], a["id"])
    assign(client, p["id"], b["id"])
    allocate(client, p["id"], a["id"], 1)
    allocate(client, p["id"], b["id"], 1)
    data = board(client, week=WEEK, project_id=a["id"])
    assert [row["id"] for row in data["projects"]] == [a["id"]]


# ---------------------------------------------------------------- 暂停与阻塞


def test_on_hold_keeps_overdue_and_blocked(client):
    p = person(client, "傅相杰")
    pr = project(client, "北京仓储", state="on-hold")
    assign(client, p["id"], pr["id"])
    milestone(client, pr["id"], "逾期节点", commit_date="2026-10-25", state="进行中")
    milestone(client, pr["id"], "阻塞节点", commit_date="2026-11-04", state="外部阻塞")
    allocate(client, p["id"], pr["id"], 2)

    data = board(client, week=WEEK)
    row = data["projects"][0]
    assert row["state"] == "on-hold"
    assert row["on_hold"] is True
    assert row["overdue_count"] == 1
    assert "overdue" in kinds(data)
    assert "blocked" in kinds(data)
    blocked = [t for t in data["todos"] if t["kind"] == "blocked"]
    assert blocked[0]["project_state"] == "on-hold"


# ---------------------------------------------------------------- 空态


def test_empty_state_only_when_no_anomaly_and_no_missing(client):
    p = person(client, "傅相杰")
    pr = project(client, "贵州V1.5")
    assign(client, p["id"], pr["id"])
    allocate(client, p["id"], pr["id"], 2)
    assert client.put(
        f"/api/persons/{p['id']}/weeks/{WEEK}/review", json={"reviewed": True}
    ).status_code == 200

    data = board(client, week=WEEK)
    assert data["todos"] == []
    assert data["has_pending"] is False


def test_missing_capacity_keeps_pending(client):
    p = person(client, "傅相杰", capacity=None)
    pr = project(client, "贵州V1.5")
    assign(client, p["id"], pr["id"])
    allocate(client, p["id"], pr["id"], 2)
    data = board(client, week=WEEK)
    assert data["has_pending"] is True
    assert "capacity" in kinds(data)


def test_unfilled_allocation_is_pending(client):
    p = person(client, "傅相杰")
    pr = project(client, "贵州V1.5")
    assign(client, p["id"], pr["id"])
    ms = milestone(
        client, pr["id"], "已分派未填投入", commit_date="2026-11-05", state="进行中",
        assignee_id=p["id"],
    )
    data = board(client, week=WEEK)
    assert data["has_pending"] is True
    assert any(
        t["kind"] == "missing_allocation" and t["milestone_id"] == ms["id"]
        for t in data["todos"]
    )


# ---------------------------------------------------------------- 其他


def test_priority_order(client):
    p = person(client, "傅相杰")
    low = project(client, "低优先", priority="P3")
    high = project(client, "高优先", priority="P1")
    mid = project(client, "中优先", priority="P2")
    for pr in (low, high, mid):
        assign(client, p["id"], pr["id"])
    data = board(client, week=WEEK)
    assert [row["id"] for row in data["projects"]] == [high["id"], mid["id"], low["id"]]


def test_current_focus_is_manual(client):
    p = person(client, "傅相杰")
    pr = project(client, "贵州V1.5")
    assign(client, p["id"], pr["id"])
    ms = milestone(client, pr["id"], "手动重点", commit_date="2026-11-20", state="未开始")
    other = milestone(client, pr["id"], "更早到期", commit_date="2026-11-03", state="进行中")
    r = client.patch(
        f"/api/projects/{pr['id']}",
        json={"current_focus_milestone_id": ms["id"]},
    )
    assert r.status_code == 200
    data = board(client, week=WEEK)
    row = data["projects"][0]
    assert row["current_focus_milestone_id"] == ms["id"]
    assert row["current_focus_name"] == "手动重点"


def test_week_must_be_monday(client):
    r = client.get("/api/workbench", params={"week": "2026-11-03"})
    assert r.status_code == 422


def test_person_card_matches_person_page(client):
    """三页同源：工作台人员卡与人员页 /api/persons/{id}/weeks/{week} 完全一致。"""
    p = person(client, "傅相杰")
    pr = project(client, "贵州V1.5")
    assign(client, p["id"], pr["id"])
    alloc = allocate(client, p["id"], pr["id"], 3)
    data = board(client, week=WEEK)
    card = data["people"][0]
    page = client.get(f"/api/persons/{p['id']}/weeks/{WEEK}").json()
    assert card["total_days"] == page["total_days"]
    assert card["allocations"][0]["id"] == alloc["id"]
    assert card["allocations"][0]["id"] == page["allocations"][0]["id"]


# ---------------------------------------------------------------- 评审修复
# 整分支评审的 Important / 重级 Minor：以下 6 条为回归用例。


def test_milestone_assignee_in_scope_is_listed_and_pending(client):
    """节点执行人即使没有职责记录，也要在工作台出现并看到待补数据。"""
    p = person(client, "傅相杰", capacity=None)
    pr = project(client, "贵州V1.5")
    ms = milestone(
        client,
        pr["id"],
        "节点执行",
        commit_date="2026-11-05",
        state="进行中",
        assignee_id=p["id"],
    )
    data = board(client, week=WEEK)
    assert [c["person_id"] for c in data["people"]] == [p["id"]]
    assert "capacity" in kinds(data)
    assert any(
        t["kind"] == "missing_allocation" and t["milestone_id"] == ms["id"]
        for t in data["todos"]
    )


def test_filter_excludes_person_without_relation_to_scope(client):
    """按项目过滤时，与该项目无关的人不进入人员区。"""
    a = project(client, "贵州V1.5")
    b = project(client, "卡鉴")
    inside = person(client, "赵辉辉")
    outside = person(client, "傅相杰")
    assign(client, inside["id"], a["id"])
    assign(client, outside["id"], b["id"])
    allocate(client, inside["id"], a["id"], 1)
    allocate(client, outside["id"], b["id"], 1)
    data = board(client, week=WEEK, project_id=a["id"])
    assert [c["person_id"] for c in data["people"]] == [inside["id"]]


def test_over_capacity_is_pending(client):
    """已填投入超出容量必须进入待处理事项。"""
    p = person(client, "傅相杰", capacity=2.0)
    pr = project(client, "贵州V1.5")
    assign(client, p["id"], pr["id"])
    allocate(client, p["id"], pr["id"], 3)
    data = board(client, week=WEEK)
    assert "over_capacity" in kinds(data)
    over = [t for t in data["todos"] if t["kind"] == "over_capacity"]
    assert over[0]["person_id"] == p["id"]
    assert over[0]["week_label"] == "2026-11-02 ~ 2026-11-08"


def test_missing_commit_date_is_pending(client):
    """未填承诺日期的未完成节点属于待补数据。"""
    p = person(client, "傅相杰")
    pr = project(client, "贵州V1.5")
    assign(client, p["id"], pr["id"])
    ms = milestone(
        client, pr["id"], "缺承诺日期", state="未开始", assignee_id=p["id"]
    )
    data = board(client, week=WEEK)
    assert any(
        t["kind"] == "missing_date" and t["milestone_id"] == ms["id"]
        for t in data["todos"]
    )


def test_done_project_overdue_still_visible(client):
    """已完成项目不进入项目一览，但其未完成节点的逾期仍然可见。"""
    p = person(client, "傅相杰")
    pr = project(client, "已结项", state="done")
    assign(client, p["id"], pr["id"])
    ms = milestone(
        client, pr["id"], "结项前逾期", commit_date="2026-10-20", state="进行中"
    )
    allocate(client, p["id"], pr["id"], 1)
    data = board(client, week=WEEK)
    assert [row["id"] for row in data["projects"]] == []
    assert any(
        t["kind"] == "overdue" and t["milestone_id"] == ms["id"] for t in data["todos"]
    )


def test_terminal_milestone_with_legacy_blocker_not_blocked(client):
    """已完成节点即使残留旧的阻塞说明，也不再算阻塞待处理。"""
    p = person(client, "傅相杰")
    pr = project(client, "贵州V1.5")
    assign(client, p["id"], pr["id"])
    ms = milestone(
        client,
        pr["id"],
        "已完成节点",
        commit_date="2026-10-20",
        state="已完成",
        assignee_id=p["id"],
    )
    r = client.patch(
        f"/api/milestones/{ms['id']}", json={"blocker_reason": "历史遗留说明"}
    )
    assert r.status_code == 200, r.text
    data = board(client, week=WEEK)
    assert "blocked" not in kinds(data)
