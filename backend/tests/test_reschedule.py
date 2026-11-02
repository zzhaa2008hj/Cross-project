from datetime import date

import pytest

from app.services import reschedule as reschedule_service
from tests.conftest import link, make_milestone, make_project


def build_diamond(db):
    """A -> B, A -> C, B/C -> D（菱形），另有一个已完成节点 E。"""
    project = make_project(db, "菱形项目")
    a = make_milestone(
        db, project, "A", start_date=date(2026, 11, 2), commit_date=date(2026, 11, 13),
        state="进行中",
    )
    b = make_milestone(
        db, project, "B", start_date=date(2026, 11, 16), commit_date=date(2026, 11, 20),
        state="未开始",
    )
    c = make_milestone(
        db, project, "C", start_date=date(2026, 11, 16), commit_date=date(2026, 11, 20),
        state="未开始",
    )
    d = make_milestone(
        db, project, "D", start_date=date(2026, 11, 23), commit_date=date(2026, 11, 27),
        state="未开始",
    )
    e = make_milestone(
        db, project, "E", start_date=date(2026, 11, 2), commit_date=date(2026, 11, 5),
        state="已完成",
    )
    link(db, b.id, a.id)
    link(db, c.id, a.id)
    link(db, d.id, b.id)
    link(db, d.id, c.id)
    return project, a, b, c, d, e


def test_cascade_shifts_each_successor_once(db):
    """A 延后 2 天：B/C/D 各只平移 2 天（菱形不叠加）。"""
    project, a, b, c, d, e = build_diamond(db)
    preview = reschedule_service.create_preview(db, a.id, date(2026, 11, 15), None, "cascade")
    assert preview["delta_days"] == 2
    changes = {ch["name"]: ch for ch in preview["changes"]}
    assert changes["B"]["new_commit_date"] == "2026-11-22"
    assert changes["C"]["new_commit_date"] == "2026-11-22"
    assert changes["D"]["new_commit_date"] == "2026-11-29"
    assert set(changes) == {"A", "B", "C", "D"}


def test_current_mode_only_touches_target(db):
    project, a, b, c, d, e = build_diamond(db)
    preview = reschedule_service.create_preview(db, a.id, date(2026, 11, 15), None, "current")
    assert len(preview["changes"]) == 1
    result = reschedule_service.apply_preview(db, preview["preview_id"], "客户原因", "current")
    assert [u["name"] for u in result["updated"]] == ["A"]
    db.refresh(a)
    db.refresh(b)
    assert a.commit_date == date(2026, 11, 15)
    assert b.commit_date == date(2026, 11, 20)


def test_cascade_apply_requires_cascade_preview(db):
    """仅当前节点的预览不能直接联动提交，必须整笔拒绝并提示重新预览。"""
    project, a, b, c, d, e = build_diamond(db)
    preview = reschedule_service.create_preview(db, a.id, date(2026, 11, 15), None, "current")
    with pytest.raises(reschedule_service.RescheduleError) as exc:
        reschedule_service.apply_preview(db, preview["preview_id"], "客户原因", "cascade")
    assert exc.value.status_code == 400
    assert "重新生成联动预览" in exc.value.message
    db.refresh(a)
    db.refresh(b)
    assert a.commit_date == date(2026, 11, 13)
    assert b.commit_date == date(2026, 11, 20)



def test_apply_cascade_writes_history_with_reason(db):
    project, a, b, c, d, e = build_diamond(db)
    preview = reschedule_service.create_preview(db, a.id, date(2026, 11, 15), None, "cascade")
    result = reschedule_service.apply_preview(db, preview["preview_id"], "客户原因", "cascade")
    assert {u["name"] for u in result["updated"]} == {"A", "B", "C", "D"}
    db.refresh(b)
    db.refresh(c)
    db.refresh(d)
    assert b.commit_date == date(2026, 11, 22)
    assert c.commit_date == date(2026, 11, 22)
    assert d.commit_date == date(2026, 11, 29)


def test_done_and_cancelled_are_listed_but_not_modified(db):
    project, a, b, c, d, e = build_diamond(db)
    link(db, e.id, a.id)  # E 依赖 A（E 是后继）
    e.state = "已取消"
    db.commit()
    preview = reschedule_service.create_preview(db, a.id, date(2026, 11, 15), None, "cascade")
    names = {x["name"] for x in preview["affected_not_modified"]}
    assert "E" in names
    assert "E" not in {ch["name"] for ch in preview["changes"]}


def test_empty_dates_stay_empty(db):
    project = make_project(db, "空日期项目")
    a = make_milestone(db, project, "A", start_date=date(2026, 11, 2), commit_date=date(2026, 11, 13))
    b = make_milestone(db, project, "B", start_date=None, commit_date=None, state="未开始")
    link(db, b.id, a.id)
    preview = reschedule_service.create_preview(db, a.id, date(2026, 11, 15), None, "cascade")
    changes = {ch["name"]: ch for ch in preview["changes"]}
    assert "B" not in changes
    assert any(x["name"] == "B" for x in preview["affected_not_modified"])


def test_cycle_is_rejected_whole(db):
    project = make_project(db, "环项目")
    a = make_milestone(db, project, "A")
    b = make_milestone(db, project, "B")
    link(db, b.id, a.id)
    link(db, a.id, b.id)
    with pytest.raises(reschedule_service.RescheduleError) as exc:
        reschedule_service.create_preview(db, a.id, date(2026, 11, 15), None, "cascade")
    assert exc.value.status_code == 400
    assert "循环" in exc.value.message


def test_invalid_date_is_rejected_whole(db):
    """源节点开始日晚于承诺日，改期后仍非法 → 预览阶段即整笔拒绝且不写半份历史。"""
    project = make_project(db, "非法日期项目")
    a = make_milestone(
        db, project, "A", start_date=date(2026, 11, 20), commit_date=date(2026, 11, 13)
    )
    with pytest.raises(reschedule_service.RescheduleError) as exc:
        reschedule_service.create_preview(db, a.id, date(2026, 11, 15), None, "current")
    assert exc.value.status_code == 400
    assert "开始日晚于承诺日" in exc.value.message
    db.refresh(a)
    assert a.commit_date == date(2026, 11, 13)
    assert a.start_date == date(2026, 11, 20)
    assert a.version == 1


def test_preview_rejects_new_start_after_new_commit(db):
    """IMP-1：预览阶段即拒绝「新开始日 > 新承诺日」的输入。"""
    project = make_project(db, "预览非法日期项目")
    a = make_milestone(
        db, project, "A", start_date=date(2026, 11, 2), commit_date=date(2026, 11, 13)
    )
    with pytest.raises(reschedule_service.RescheduleError) as exc:
        reschedule_service.create_preview(
            db, a.id, date(2026, 11, 13), date(2026, 11, 20), "current"
        )
    assert exc.value.status_code == 400
    assert "开始日晚于承诺日" in exc.value.message
    assert exc.value.detail["milestone_id"] == a.id
    db.refresh(a)
    assert a.start_date == date(2026, 11, 2)
    assert a.commit_date == date(2026, 11, 13)
    assert a.version == 1


def test_preview_rejects_inverted_successor_in_cascade(db):
    """IMP-1：联动后继的开始日晚于承诺日时，预览同样整笔拒绝（与提交一致）。"""
    project = make_project(db, "联动非法日期项目")
    a = make_milestone(
        db, project, "A", start_date=date(2026, 11, 2), commit_date=date(2026, 11, 13)
    )
    b = make_milestone(
        db, project, "B", start_date=date(2026, 11, 20), commit_date=date(2026, 11, 15)
    )
    link(db, b.id, a.id)
    with pytest.raises(reschedule_service.RescheduleError) as exc:
        reschedule_service.create_preview(db, a.id, date(2026, 11, 15), None, "cascade")
    assert exc.value.status_code == 400
    assert "开始日晚于承诺日" in exc.value.message
    assert exc.value.detail["milestone_id"] == b.id
    db.refresh(b)
    assert b.start_date == date(2026, 11, 20)
    assert b.commit_date == date(2026, 11, 15)


def test_apply_rejects_legacy_invalid_preview(db):
    """IMP-1：守卫上线前的历史预览在提交阶段同样整笔拒绝（预览/提交一致）。"""
    import json

    project = make_project(db, "历史非法预览项目")
    a = make_milestone(
        db, project, "A", start_date=date(2026, 11, 2), commit_date=date(2026, 11, 13)
    )
    payload = {
        "milestone_id": a.id,
        "milestone_name": "A",
        "project_id": project.id,
        "mode": "current",
        "delta_days": 0,
        "old_commit_date": "2026-11-13",
        "new_commit_date": "2026-11-13",
        "old_start_date": "2026-11-02",
        "new_start_date": "2026-11-20",
        "changes": [
            {
                "milestone_id": a.id,
                "name": "A",
                "state": "进行中",
                "old_start_date": "2026-11-02",
                "old_commit_date": "2026-11-13",
                "new_start_date": "2026-11-20",
                "new_commit_date": "2026-11-13",
                "note": "",
            }
        ],
        "affected_not_modified": [],
        "buffer": {},
        "successor_count": 0,
        "impact_ids": [a.id],
    }
    row = reschedule_service.ReschedulePreview(
        milestone_id=a.id,
        mode="current",
        payload_json=json.dumps(payload, ensure_ascii=False),
        versions_json=json.dumps({str(a.id): a.version}),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    with pytest.raises(reschedule_service.RescheduleError) as exc:
        reschedule_service.apply_preview(db, row.id, "历史预览", "current")
    assert exc.value.status_code == 400
    assert "开始日晚于承诺日" in exc.value.message
    db.refresh(a)
    assert a.start_date == date(2026, 11, 2)
    assert a.commit_date == date(2026, 11, 13)
    assert a.version == 1


def test_empty_date_semantics_unchanged(db):
    """IMP-1 不改变空日期语义：单边留空按平移/保留，两个都空仍报「必须给出日期」。"""
    project = make_project(db, "空日期语义项目")
    a = make_milestone(
        db, project, "A", start_date=date(2026, 11, 2), commit_date=date(2026, 11, 13)
    )
    preview = reschedule_service.create_preview(db, a.id, date(2026, 11, 15), None, "current")
    assert preview["new_start_date"] == "2026-11-04"
    assert preview["new_commit_date"] == "2026-11-15"

    with pytest.raises(reschedule_service.RescheduleError) as exc:
        reschedule_service.create_preview(db, a.id, None, None, "current")
    assert exc.value.status_code == 400
    assert "必须给出新的承诺日或开始日" in exc.value.message


def test_version_conflict_rejects_whole(db):
    project, a, b, c, d, e = build_diamond(db)
    preview = reschedule_service.create_preview(db, a.id, date(2026, 11, 15), None, "cascade")
    b.version = 99
    db.commit()
    with pytest.raises(reschedule_service.RescheduleError) as exc:
        reschedule_service.apply_preview(db, preview["preview_id"], "冲突", "cascade")
    assert exc.value.status_code == 409
    assert "refreshed_preview" in exc.value.detail
    db.refresh(a)
    db.refresh(b)
    assert a.commit_date == date(2026, 11, 13)
    assert b.commit_date == date(2026, 11, 20)


def test_reason_is_required(db):
    project, a, b, c, d, e = build_diamond(db)
    preview = reschedule_service.create_preview(db, a.id, date(2026, 11, 15), None, "cascade")
    with pytest.raises(reschedule_service.RescheduleError) as exc:
        reschedule_service.apply_preview(db, preview["preview_id"], "  ", "cascade")
    assert exc.value.status_code == 400


def test_cross_project_dependency_unsupported(db):
    p1 = make_project(db, "项目一")
    p2 = make_project(db, "项目二")
    a = make_milestone(db, p1, "A")
    b = make_milestone(db, p2, "B")
    link(db, b.id, a.id)
    with pytest.raises(reschedule_service.RescheduleError) as exc:
        reschedule_service.create_preview(db, a.id, date(2026, 11, 15), None, "cascade")
    assert exc.value.status_code == 400
    assert "跨项目" in exc.value.message
