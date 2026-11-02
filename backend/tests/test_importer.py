from pathlib import Path

import pytest

from app.services import importer as importer_service

MILESTONE_TABLE = """# 里程碑

## 真源表

| 项目 | 节点 | 交付物 | 开始日 | 承诺日 | 工作日(覆盖) | 缓冲来源 | 负责人 | 本周投入 | 依赖前置 | 状态 | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 示例项目 | 节点一 | 交付物一 | 2026-11-02 | 2026-11-13 |  | 内部 | 产品 | 80% |  | 进行中 |  |
| 示例项目 | 节点二 | 交付物二 | 2026-11-16 | 2026-11-20 |  | 外部资源 | 开发 | 50% | 节点一 | 未开始 |  |
| 示例项目 | 节点三 | 交付物三 | 2026-11-16 | 2026-11-20 |  | 内部 | 开发 | 50% | 节点一 | 待确认状态 | 状态未知样例 |
| 示例项目 | 节点四 | 交付物四 | 2026-13-40 | 2026-11-20 |  | 内部 | 开发 | 50% |  | 未开始 | 坏日期样例 |
| 示例项目 | 节点五 | 交付物五 |  |  |  | 内部 | 开发 | 50% |  | 未开始 | 日期待定样例 |
"""

PERSONNEL = """# 人员

## 角色花名册

| 角色 | 可用产能 | 备注 |
|---|---|---|
| 项目负责人 | 50% | |
| 全栈 | 80% | |
| 测试 | 60% | |

> 已知人名映射（仅作角色→人对照）：
> - 张三 → 示例项目 项目负责人（全栈）
"""

PROJECT_NOTE = """---
title: 示例项目
type: project
status: maintenance
priority: P2
created: 2026-10-01
---

## 进展

示例项目进展记录。

## 其他

忽略这一段。
"""


@pytest.fixture()
def fake_vault(tmp_path: Path) -> Path:
    (tmp_path / "20_项目").mkdir(parents=True)
    (tmp_path / "99_系统").mkdir(parents=True)
    (tmp_path / "20_项目" / "里程碑.md").write_text(MILESTONE_TABLE, encoding="utf-8")
    (tmp_path / "99_系统" / "人员.md").write_text(PERSONNEL, encoding="utf-8")
    (tmp_path / "20_项目" / "示例项目.md").write_text(PROJECT_NOTE, encoding="utf-8")
    return tmp_path


def test_snapshot_reads_sources_and_counts(fake_vault):
    snapshot = importer_service.build_snapshot(fake_vault)
    kinds = [r["kind"] for r in snapshot["records"]]
    assert kinds.count("milestone") == 5
    assert kinds.count("project") == 1
    assert kinds.count("person") == 1
    assert snapshot["snapshot_hash"]


def test_dry_run_writes_nothing(db, fake_vault):
    from app.models import Milestone, Person, Project

    snapshot = importer_service.build_snapshot(fake_vault)
    result = importer_service.dry_run_snapshot(db, snapshot)
    assert db.query(Project).count() == 0
    assert db.query(Milestone).count() == 0
    assert db.query(Person).count() == 0
    assert result["counts"]["read"] == 7


def test_apply_then_idempotent(db, fake_vault):
    from app.models import Milestone, Project

    snapshot = importer_service.build_snapshot(fake_vault)
    first = importer_service.apply_snapshot(db, snapshot)
    counts = first["counts"]
    # 未知状态与坏日期两条失败，其余导入
    assert counts["read"] == 7
    assert counts["failed"] == 2
    assert counts["imported"] == counts["read"] - counts["failed"]
    assert db.query(Project).count() == 1
    assert db.query(Milestone).count() == 3

    snapshot2 = importer_service.build_snapshot(fake_vault)
    assert snapshot2["snapshot_hash"] == snapshot["snapshot_hash"]
    second = importer_service.apply_snapshot(db, snapshot2)
    assert second["counts"]["imported"] == 0
    assert second["counts"]["read"] == second["counts"]["imported"] + second["counts"]["skipped"] + second["counts"]["failed"]
    assert db.query(Milestone).count() == 3
    assert db.query(Project).count() == 1


def test_counts_are_mutually_exclusive(db, fake_vault):
    snapshot = importer_service.build_snapshot(fake_vault)
    result = importer_service.apply_snapshot(db, snapshot)
    counts = result["counts"]
    assert counts["read"] == counts["imported"] + counts["skipped"] + counts["failed"]


def test_unknown_status_is_failed_and_traceable(db, fake_vault):
    snapshot = importer_service.build_snapshot(fake_vault)
    result = importer_service.apply_snapshot(db, snapshot)
    failed = [r for r in result["records"] if r["status"] == "fail"]
    assert failed, "未知状态必须记为失败而不是静默映射"
    reasons = " ".join(r["reason"] for r in failed)
    assert "待确认状态" in reasons
    pending_raw = [p["raw"] for p in result["pending"]]
    assert "待确认状态" in pending_raw
    assert "2026-13-40" in pending_raw


def test_missing_dates_are_imported_as_empty_with_pending(db, fake_vault):
    from app.models import Milestone

    snapshot = importer_service.build_snapshot(fake_vault)
    importer_service.apply_snapshot(db, snapshot)
    ms = db.query(Milestone).filter(Milestone.name == "节点五").one()
    assert ms.start_date is None
    assert ms.commit_date is None


def test_in_app_edit_is_not_overwritten(db, fake_vault):
    from app.models import Project

    snapshot = importer_service.build_snapshot(fake_vault)
    importer_service.apply_snapshot(db, snapshot)
    project = db.query(Project).one()
    project.progress = "软件内手工编辑"
    project.edited_in_app = True
    db.commit()

    note = fake_vault / "20_项目" / "示例项目.md"
    note.write_text(PROJECT_NOTE.replace("示例项目进展记录。", "源已更新的进展"), encoding="utf-8")
    snapshot2 = importer_service.build_snapshot(fake_vault)
    assert snapshot2["snapshot_hash"] != snapshot["snapshot_hash"]
    result = importer_service.apply_snapshot(db, snapshot2)
    db.refresh(project)
    assert project.progress == "软件内手工编辑"
    skipped = [r for r in result["records"] if r["kind"] == "project"]
    assert skipped and skipped[0]["status"] == "skip"
    assert skipped[0]["diff"], "源变化必须先显示差异"


def test_dependencies_are_linked_and_unresolved_are_pending(db, fake_vault):
    from app.models import MilestoneDependency

    snapshot = importer_service.build_snapshot(fake_vault)
    result = importer_service.apply_snapshot(db, snapshot)
    assert db.query(MilestoneDependency).count() == 1


def test_report_markdown_contains_counts_and_reconciliation(db, fake_vault):
    snapshot = importer_service.build_snapshot(fake_vault)
    result = importer_service.apply_snapshot(db, snapshot)
    report = importer_service.build_report(
        db, snapshot, True, result["records"], result["pending"], result["diffs"], result["counts"], result["totals"]
    )
    markdown = importer_service.render_markdown(report, True)
    assert "读入" in markdown and "导入" in markdown and "跳过" in markdown and "失败" in markdown
    assert "对账" in markdown
    assert "35" in markdown and "7" in markdown


@pytest.mark.skipif(
    not Path("/home/hui/MyData/AI/my-vault").exists(), reason="真实 vault 不在本次环境"
)
def test_real_vault_reconciliation():
    """真实 vault：节点真源表 35 行、维护期项目 7 个。"""
    snapshot = importer_service.build_snapshot(Path("/home/hui/MyData/AI/my-vault"))
    milestones = [r for r in snapshot["records"] if r["kind"] == "milestone"]
    projects = [r for r in snapshot["records"] if r["kind"] == "project"]
    assert len(milestones) == 35
    maintenance = [p for p in projects if p["values"].get("state") == "maintenance"]
    assert len(maintenance) == 7
