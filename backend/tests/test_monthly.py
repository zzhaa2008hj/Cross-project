from datetime import date

import pytest
from fastapi import HTTPException

from app.models import Allocation, Assignment, Person, Project, WeekReview
from app.services import monthly as monthly_service
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


# ------------------------------------------------------------------ Task 3：人员总表 roster


def _roster(client, month="2026-11", include_archived=False):
    r = client.get(
        "/api/persons/roster",
        params={"month": month, "include_archived": include_archived},
    )
    assert r.status_code == 200
    return r.json()


def test_roster_lists_active_people_sorted_by_name(client, db):
    a = _person(db, "张三2")
    b = _person(db, "傅相杰")
    body = _roster(client)
    assert [p["name"] for p in body["people"]] == ["傅相杰", "张三2"]
    assert body["month"] == "2026-11"
    assert len(body["weeks"]) == 5


def test_roster_excludes_archived_by_default_and_appends_at_end(client, db):
    active = _person(db, "傅相杰")
    dead = _person(db, "张三2")
    dead.archived = True
    db.commit()

    assert [p["name"] for p in _roster(client)["people"]] == ["傅相杰"]

    body = _roster(client, include_archived=True)
    assert [p["name"] for p in body["people"]] == ["傅相杰", "张三2"]
    assert body["people"][-1]["archived"] is True
    assert body["people"][0]["archived"] is False


def test_roster_invalid_month_returns_400(client, db):
    for bad in ("2026-13", "2026-1", "abc", ""):
        assert client.get("/api/persons/roster", params={"month": bad}).status_code == 400


def test_roster_empty_month_still_lists_weeks(client, db):
    body = _roster(client, month="2027-02")
    assert body["people"] == []
    assert body["weeks"] == ["2027-02-01", "2027-02-08", "2027-02-15", "2027-02-22"]


def test_archived_person_absent_from_roster_but_detail_ok(client, db):
    dead = _person(db, "张三2")
    dead.archived = True
    proj = _project(db, "贵州矿产预测")
    _alloc(db, dead, proj, "2026-11-02", 10)
    db.commit()

    assert [p["name"] for p in _roster(client)["people"]] == []

    detail = client.get(f"/api/persons/{dead.id}/month", params={"month": "2026-11"})
    assert detail.status_code == 200
    assert detail.json()["used_days"] == 10


def test_roster_and_detail_agree_on_used_days(client, db):
    p = _person(db, "傅相杰")
    proj = _project(db, "贵州矿产预测")
    _alloc(db, p, proj, "2026-11-02", 10)
    _alloc(db, p, proj, "2026-11-09", 5)
    _alloc(db, p, proj, "2026-11-30", 4.5)

    from_roster = _roster(client)["people"][0]
    from_detail = client.get(f"/api/persons/{p.id}/month", params={"month": "2026-11"}).json()
    assert from_roster["used_days"] == from_detail["used_days"] == 19.5
    assert from_roster["remaining_days"] == from_detail["remaining_days"]
    assert from_roster["reviewed"] == from_detail["reviewed"]
    assert [x["project_id"] for x in from_roster["projects"]] == [
        x["project_id"] for x in from_detail["projects"]
    ]


def test_roster_projects_merge_allocation_and_assignment_with_roles(client, db):
    p = _person(db, "傅相杰")
    p1 = _project(db, "贵州矿产预测")
    p2 = _project(db, "北京仓储")
    _alloc(db, p, p1, "2026-11-02", 10)
    db.add(Assignment(person_id=p.id, project_id=p2.id, role="项目负责人"))
    db.add(Assignment(person_id=p.id, project_id=p2.id, role="业务对接"))
    db.commit()

    row = _roster(client)["people"][0]
    # projects 按 project_id 升序（见本 Task Step 4 第 7 步），所以 p1 在前、p2 在后；
    # 但仍用 id 索引，别靠位置——位置一旦写反，测试会静默通过错误的排序。
    by_id = {u["project_id"]: u for u in row["projects"]}
    assert by_id[p1.id] == {
        "project_id": p1.id, "project_name": "贵州矿产预测", "roles": [],
        "days": 10.0, "has_allocation": True, "has_assignment": False,
    }
    assert by_id[p2.id] == {
        "project_id": p2.id, "project_name": "北京仓储",
        "roles": ["项目负责人", "业务对接"],
        "days": 0.0, "has_allocation": False, "has_assignment": True,
    }
    # 排序本身另钉一条：project_id 升序
    assert [u["project_id"] for u in row["projects"]] == sorted(u["project_id"] for u in row["projects"])


# ------------------------------------------------------------------ Task 2 审查 Minor 回归


def test_month_primitives_pure_function_regressions():
    """不走 HTTP，直接调月度原语：周集合与月份解析的边界。"""
    assert monthly_service.month_weeks("2027-02") == [
        "2027-02-01", "2027-02-08", "2027-02-15", "2027-02-22",
    ]
    last_weeks = monthly_service.month_weeks("9999-12")
    assert len(last_weeks) == 4
    assert last_weeks[-1] == "9999-12-27"
    with pytest.raises(HTTPException) as excinfo:
        monthly_service.parse_month("0000-01")
    assert excinfo.value.status_code == 400


def test_person_month_unknown_person_returns_404(client, db):
    r = client.get("/api/persons/999999/month", params={"month": "2026-11"})
    assert r.status_code == 404


def test_person_month_missing_month_param_returns_422(client, db):
    p = _person(db)
    r = client.get(f"/api/persons/{p.id}/month")
    assert r.status_code == 422


def test_allocation_huge_days_returns_422_not_500(client, db):
    """人天是 400 位整数的 JSON 字面量时必须 422：float() 会抛 OverflowError，
    而 Pydantic v2 只把 ValueError/AssertionError 转成校验错误。"""
    p = _person(db)
    proj = _project(db, "贵州矿产预测")
    r = client.post(
        "/api/allocations",
        json={
            "person_id": p.id,
            "project_id": proj.id,
            "week": "2026-11-02",
            "days": 10 ** 400,
        },
    )
    assert r.status_code == 422
