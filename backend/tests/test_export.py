"""E4 Task 2：JSON / Markdown / Obsidian 摘要导出与预览差异。"""
import sqlite3
from pathlib import Path

from app.services.export import (
    build_export,
    diff_exports,
    render_markdown,
    render_obsidian_summary,
)


def _make_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT, state TEXT,"
        " progress REAL, note TEXT, archived INTEGER)"
    )
    conn.execute(
        "CREATE TABLE milestones (id INTEGER PRIMARY KEY, project_id INTEGER,"
        " name TEXT, state TEXT, archived INTEGER)"
    )
    conn.execute(
        "CREATE TABLE week_capacities (id INTEGER PRIMARY KEY, person_id INTEGER,"
        " week TEXT, days REAL)"
    )
    conn.execute(
        "CREATE TABLE history_entries (id INTEGER PRIMARY KEY, entity_type TEXT,"
        " entity_id INTEGER, entity_name TEXT, action TEXT, created_at TEXT)"
    )
    return conn


def _seeded_db(tmp_path: Path) -> Path:
    path = tmp_path / "export.db"
    conn = _make_db(path)
    conn.execute(
        "INSERT INTO projects (id,name,state,progress,note,archived) VALUES (1,'甲项目','active',0.5,'',0)"
    )
    conn.execute(
        "INSERT INTO projects (id,name,state,progress,note,archived) VALUES (2,'乙项目','on-hold',NULL,'',0)"
    )
    conn.execute(
        "INSERT INTO milestones (id,project_id,name,state,archived) VALUES (1,1,'节点A','进行中',0)"
    )
    conn.execute(
        "INSERT INTO week_capacities (id,person_id,week,days) VALUES (1,7,'2026-W44',NULL)"
    )
    conn.execute(
        "INSERT INTO week_capacities (id,person_id,week,days) VALUES (2,8,'2026-W44',0.0)"
    )
    conn.execute(
        "INSERT INTO history_entries (id,entity_type,entity_id,entity_name,action,created_at)"
        " VALUES (1,'project',1,'甲项目','create','2026-11-01T10:00:00')"
    )
    conn.commit()
    conn.close()
    return path


def test_build_export_counts_rows_and_has_snapshot_id(tmp_path):
    export = build_export(_seeded_db(tmp_path))
    assert export["schema_version"] == 1
    assert export["counts"]["projects"] == 2
    assert export["counts"]["milestones"] == 1
    assert export["snapshot_id"].startswith("snap-")
    assert export["generated_at"]


def test_build_export_content_hash_is_stable_for_same_content(tmp_path):
    db = _seeded_db(tmp_path)
    first = build_export(db)
    second = build_export(db)
    # snapshot_id 含 UTC 时间戳，两次生成可能不同；内容散列部分必须一致
    assert first["snapshot_id"].rsplit("-", 1)[1] == second["snapshot_id"].rsplit("-", 1)[1]
    assert first["tables"] == second["tables"]


def test_build_export_preserves_null_capacity(tmp_path):
    export = build_export(_seeded_db(tmp_path))
    rows = {r["id"]: r for r in export["tables"]["week_capacities"]}
    assert rows[1]["days"] is None
    assert rows[2]["days"] == 0.0


def test_build_export_carries_column_metadata(tmp_path):
    export = build_export(_seeded_db(tmp_path))
    names = [c["name"] for c in export["columns"]["projects"]]
    assert names == ["id", "name", "state", "progress", "note", "archived"]
    pk = [c["name"] for c in export["columns"]["projects"] if c["pk"]]
    assert pk == ["id"]


def test_render_markdown_contains_every_table(tmp_path):
    export = build_export(_seeded_db(tmp_path))
    markdown = render_markdown(export)
    assert "projects" in markdown
    assert "week_capacities" in markdown
    assert "甲项目" in markdown
    assert "节点A" in markdown


def test_render_markdown_marks_null_distinctly(tmp_path):
    export = build_export(_seeded_db(tmp_path))
    markdown = render_markdown(export)
    assert "_NULL_" in markdown


def test_render_obsidian_summary_lists_projects_and_unknown_capacity(tmp_path):
    export = build_export(_seeded_db(tmp_path))
    summary = render_obsidian_summary(export)
    assert "甲项目" in summary
    assert "乙项目" in summary
    assert "未知" in summary
    assert "2026-W44" in summary


def test_diff_exports_marks_first_preview(tmp_path):
    export = build_export(_seeded_db(tmp_path))
    diff = diff_exports(None, export)
    assert diff["is_first"] is True
    assert diff["tables"]["projects"]["added"] == 2
    assert diff["tables"]["projects"]["removed"] == 0


def test_diff_exports_detects_added_changed_removed(tmp_path):
    db = _seeded_db(tmp_path)
    before = build_export(db)

    conn = sqlite3.connect(db)
    conn.execute("UPDATE projects SET state='done' WHERE id=1")
    conn.execute("DELETE FROM projects WHERE id=2")
    conn.execute(
        "INSERT INTO projects (id,name,state,progress,note,archived) VALUES (3,'丙项目','active',NULL,'',0)"
    )
    conn.commit()
    conn.close()

    after = build_export(db)
    diff = diff_exports(before, after)
    assert diff["is_first"] is False
    projects = diff["tables"]["projects"]
    assert projects["added"] == 1
    assert projects["removed"] == 1
    assert projects["changed"] == 1
    assert "3" in projects["ids"]


def test_diff_exports_ignores_unchanged_tables(tmp_path):
    db = _seeded_db(tmp_path)
    before = build_export(db)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE projects SET state='done' WHERE id=1")
    conn.commit()
    conn.close()
    after = build_export(db)
    diff = diff_exports(before, after)
    assert diff["tables"]["milestones"]["changed"] == 0
    assert diff["tables"]["milestones"]["added"] == 0


def test_build_export_carries_foreign_key_metadata(tmp_path):
    db = tmp_path / "fk.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute(
        "CREATE TABLE week_capacities (id INTEGER PRIMARY KEY,"
        " person_id INTEGER REFERENCES persons(id), week TEXT, days REAL)"
    )
    conn.commit()
    conn.close()

    export = build_export(db)

    fks = export["foreign_keys"]["week_capacities"]
    assert len(fks) == 1
    assert fks[0]["referred_table"] == "persons"
    assert fks[0]["columns"] == ["person_id"]
