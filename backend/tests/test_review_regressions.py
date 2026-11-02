"""R1–R5/R7: real import, API edits and reschedule transactions in an isolated DB."""
from datetime import date

import pytest

from app.models import HistoryEntry, Milestone, MilestoneDependency
from app.services import importer, reschedule
from .conftest import make_project, make_milestone, link
from .test_importer import fake_vault


def imported(db, vault):
    importer.apply_snapshot(db, importer.build_snapshot(vault))
    return db.query(Milestone).filter_by(name="节点一").one()


def change_source(vault, old, new):
    path = vault / "20_项目" / "里程碑.md"
    path.write_text(path.read_text().replace(old, new))


def test_reschedule_protects_target_and_cascade_from_reimport(db, fake_vault):
    a = imported(db, fake_vault)
    p = reschedule.create_preview(db, a.id, date(2026, 11, 15), None, "cascade")
    reschedule.apply_preview(db, p["preview_id"], "调整", "cascade")
    change_source(fake_vault, "交付物一", "新交付物一")
    change_source(fake_vault, "交付物二", "新交付物二")
    importer.apply_snapshot(db, importer.build_snapshot(fake_vault))
    db.expire_all()
    assert a.commit_date == date(2026, 11, 15)
    b = db.query(Milestone).filter_by(name="节点二").one()
    assert b.commit_date == date(2026, 11, 22)
    assert a.edited_in_app and b.edited_in_app


@pytest.mark.parametrize("old,new", [("2026-11-13", "2026-11-20"), ("进行中", "已完成"), ("80% |  |", "80% | 节点二 |")])
def test_import_invalidates_old_preview_atomically(db, fake_vault, old, new):
    a = imported(db, fake_vault)
    p = reschedule.create_preview(db, a.id, date(2026, 11, 15), None, "current")
    change_source(fake_vault, old, new)
    importer.apply_snapshot(db, importer.build_snapshot(fake_vault))
    before = a.commit_date
    history_count = db.query(HistoryEntry).count()
    with pytest.raises(reschedule.RescheduleError) as exc:
        reschedule.apply_preview(db, p["preview_id"], "旧预览", "current")
    assert exc.value.status_code == 409
    assert a.commit_date == before
    assert db.query(HistoryEntry).count() == history_count


@pytest.mark.parametrize("changed_source", [False, True])
def test_reimport_does_not_restore_user_deleted_dependency(db, client, fake_vault, changed_source):
    imported(db, fake_vault)
    b = db.query(Milestone).filter_by(name="节点二").one()
    assert client.patch(f"/api/milestones/{b.id}", json={"predecessor_ids": []}).status_code == 200
    assert db.query(MilestoneDependency).count() == 0
    if changed_source:
        change_source(fake_vault, "交付物二", "新交付物二")
    report = importer.apply_snapshot(db, importer.build_snapshot(fake_vault))
    assert db.query(MilestoneDependency).count() == 0
    # 依赖阶段不再重建源里已声明过、但用户已删除的边
    assert report["counts"]["imported"] == 0


@pytest.mark.parametrize("source,override", [("外部资源", None), ("内部资源", 20)])
def test_apply_buffer_matches_preview_and_get(db, client, source, override):
    project = make_project(db)
    a = make_milestone(db, project, "A", start_date=date(2026, 11, 2), commit_date=date(2026, 11, 13), buffer_source=source, workday_override=override)
    p = reschedule.create_preview(db, a.id, date(2026, 11, 15), None, "current")
    result = reschedule.apply_preview(db, p["preview_id"], "调整", "current")
    assert result["buffer"] == p["buffer"]
    assert result["buffer"] == client.get(f"/api/milestones/{a.id}").json()["buffer"]


@pytest.mark.parametrize("mutation", ["new_successor", "terminal_to_active", "empty_to_dated", "edge_removed"])
def test_cascade_rejects_changed_impact_set_without_partial_writes(db, client, mutation):
    project = make_project(db)
    a = make_milestone(db, project, "A", commit_date=date(2026, 11, 13))
    b = None
    if mutation != "new_successor":
        b = make_milestone(db, project, "B", state="已完成" if mutation == "terminal_to_active" else "未开始", commit_date=None if mutation == "empty_to_dated" else date(2026, 11, 20))
        link(db, b.id, a.id)
    p = reschedule.create_preview(db, a.id, date(2026, 11, 15), None, "cascade")
    if mutation == "new_successor":
        b = make_milestone(db, project, "B", commit_date=date(2026, 11, 20))
        link(db, b.id, a.id)
    else:
        edits = {"terminal_to_active": {"state": "进行中"}, "empty_to_dated": {"commit_date": "2026-11-20"}, "edge_removed": {"predecessor_ids": []}}
        response = client.patch(f"/api/milestones/{b.id}", json=edits[mutation])
        assert response.status_code == 200, response.text
    before = db.query(HistoryEntry).count()
    with pytest.raises(reschedule.RescheduleError) as exc:
        reschedule.apply_preview(db, p["preview_id"], "旧预览", "cascade")
    assert exc.value.status_code == 409
    assert a.commit_date == date(2026, 11, 13)
    assert db.query(HistoryEntry).count() == before


def test_import_diff_contains_values_and_record_locator(db, fake_vault):
    imported(db, fake_vault)
    change_source(fake_vault, "2026-11-13", "2026-11-20")
    report = importer.apply_snapshot(db, importer.build_snapshot(fake_vault))
    diff = next(d for d in report["diffs"] if d["field"] == "commit_date")
    assert diff["old_value"] == "2026-11-13"
    assert diff["new_value"] == "2026-11-20"
    assert "节点一" in diff["key"]
    assert diff["kind"] == "milestone"
    assert diff["source_ref"]
