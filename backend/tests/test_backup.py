"""E4 Task 3：每日一致性备份与原子发布。"""
import json
import sqlite3
from pathlib import Path

import pytest

from app.services import backup as backup_service
from app.services.backup import backup_root, run_backup, safe_join


def _seed_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT, state TEXT)")
    conn.execute(
        "INSERT INTO projects (id,name,state) VALUES (1,'甲项目','active')"
    )
    conn.commit()
    conn.close()
    return path


def test_run_backup_publishes_db_json_markdown(tmp_path):
    db = _seed_db(tmp_path / "src.db")
    root = tmp_path / "backups"

    result = run_backup(db, root, stamp="20261102T000000Z")

    assert result["stamp"] == "20261102T000000Z"
    published = root / "20261102T000000Z"
    assert (published / "crossproject.db").exists()
    assert (published / "export.json").exists()
    assert (published / "export.md").exists()
    assert (published / "obsidian.md").exists()
    assert result["counts"]["projects"] == 1
    assert Path(result["db_path"]) == published / "crossproject.db"
    assert Path(result["json_path"]) == published / "export.json"
    assert Path(result["markdown_path"]) == published / "export.md"
    assert Path(result["obsidian_path"]) == published / "obsidian.md"


def test_published_export_json_matches_published_db(tmp_path):
    db = _seed_db(tmp_path / "src.db")
    root = tmp_path / "backups"
    run_backup(db, root, stamp="20261102T000000Z")

    published = root / "20261102T000000Z"
    payload = json.loads((published / "export.json").read_text(encoding="utf-8"))
    assert payload["counts"]["projects"] == 1
    assert payload["tables"]["projects"][0]["name"] == "甲项目"

    conn = sqlite3.connect(published / "crossproject.db")
    rows = conn.execute("SELECT name FROM projects").fetchall()
    conn.close()
    assert rows == [("甲项目",)]


def test_run_backup_leaves_no_partial_publish_on_failure(tmp_path, monkeypatch):
    db = _seed_db(tmp_path / "src.db")
    root = tmp_path / "backups"

    def boom(*args, **kwargs):
        raise RuntimeError("快照失败")

    monkeypatch.setattr(backup_service, "snapshot_db", boom)
    with pytest.raises(RuntimeError):
        run_backup(db, root, stamp="20261102T000000Z")

    assert not (root / "20261102T000000Z").exists()
    assert list(root.iterdir()) == []


def test_run_backup_does_not_overwrite_existing_stamp(tmp_path):
    db = _seed_db(tmp_path / "src.db")
    root = tmp_path / "backups"
    run_backup(db, root, stamp="20261102T000000Z")
    marker = root / "20261102T000000Z" / "export.json"
    before = marker.read_text(encoding="utf-8")

    with pytest.raises(FileExistsError):
        run_backup(db, root, stamp="20261102T000000Z")
    assert marker.read_text(encoding="utf-8") == before


def test_safe_join_rejects_traversal(tmp_path):
    base = tmp_path / "backups"
    base.mkdir()
    assert safe_join(base, "20261102T000000Z") == base / "20261102T000000Z"
    with pytest.raises(ValueError):
        safe_join(base, "../escape")
    with pytest.raises(ValueError):
        safe_join(base, "a/../../escape")


def test_backup_root_defaults_under_data_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("CP_BACKUP_DIR", raising=False)
    monkeypatch.setenv("CP_DATA_DIR", str(tmp_path / "data"))
    assert backup_root() == tmp_path / "data" / "backups"


def test_backup_root_honours_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("CP_BACKUP_DIR", str(tmp_path / "custom-backups"))
    assert backup_root() == tmp_path / "custom-backups"


def test_backup_root_is_outside_vault(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("CP_VAULT_DIR", str(vault))
    monkeypatch.delenv("CP_BACKUP_DIR", raising=False)
    monkeypatch.setenv("CP_DATA_DIR", str(tmp_path / "data"))

    root = backup_root().resolve()
    assert vault.resolve() not in root.parents
    assert root != vault.resolve()
