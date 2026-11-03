"""E4 Task 3：每日一致性备份与原子发布（纯 SQLite 副本）。"""
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


def test_run_backup_publishes_sqlite_copy(tmp_path):
    db = _seed_db(tmp_path / "src.db")
    root = tmp_path / "backups"

    result = run_backup(db, root, stamp="20261102T000000Z")

    assert result["stamp"] == "20261102T000000Z"
    published = root / "20261102T000000Z"
    # 备份就是一份 SQLite 副本，不再有导出产物
    assert sorted(p.name for p in published.iterdir()) == ["crossproject.db"]
    assert Path(result["db_path"]) == published / "crossproject.db"


def test_published_db_is_readable_and_matches_source(tmp_path):
    db = _seed_db(tmp_path / "src.db")
    root = tmp_path / "backups"
    run_backup(db, root, stamp="20261102T000000Z")

    conn = sqlite3.connect(root / "20261102T000000Z" / "crossproject.db")
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
    marker = root / "20261102T000000Z" / "crossproject.db"
    before = marker.read_bytes()

    with pytest.raises(FileExistsError):
        run_backup(db, root, stamp="20261102T000000Z")
    assert marker.read_bytes() == before


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


def test_concurrent_backups_with_same_stamp_publish_exactly_once(tmp_path, monkeypatch):
    """同一版本号的并发备份：只能有一份发布成功，另一份必须报"版本已存在"。"""
    import threading
    import time

    db = _seed_db(tmp_path / "src.db")
    root = tmp_path / "backups"
    original = backup_service.snapshot_db
    barrier = threading.Barrier(2, timeout=10)

    def slow_snapshot(source, dest):
        barrier.wait()
        time.sleep(0.05)
        return original(source, dest)

    monkeypatch.setattr(backup_service, "snapshot_db", slow_snapshot)

    results: list[dict] = []
    errors: list[Exception] = []

    def worker() -> None:
        try:
            results.append(run_backup(db, root, stamp="20261102T000000Z"))
        except Exception as exc:  # noqa: BLE001  测试要看到具体异常类型
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], FileExistsError)

    published = root / "20261102T000000Z"
    assert sorted(p.name for p in published.iterdir()) == ["crossproject.db"]
    conn = sqlite3.connect(published / "crossproject.db")
    rows = conn.execute("SELECT name FROM projects").fetchall()
    conn.close()
    assert rows == [("甲项目",)]


def test_run_backup_auto_uses_free_stamp_when_version_taken(tmp_path):
    """自动挑版本号：版本已被占用时顺延，而不是直接失败。"""
    db = _seed_db(tmp_path / "src.db")
    root = tmp_path / "backups"

    first = backup_service.run_backup_auto(db, root, base="20261102T000000Z")
    second = backup_service.run_backup_auto(db, root, base="20261102T000000Z")

    assert first["stamp"] == "20261102T000000Z"
    assert second["stamp"] != first["stamp"]
    assert (root / second["stamp"] / "crossproject.db").exists()


def test_concurrent_auto_backups_get_distinct_complete_versions(tmp_path):
    """并发自动备份：版本号互不相同，每份产物都完整。"""
    import threading

    db = _seed_db(tmp_path / "src.db")
    root = tmp_path / "backups"
    results: list[dict] = []
    errors: list[Exception] = []
    barrier = threading.Barrier(4, timeout=10)

    def worker() -> None:
        try:
            barrier.wait()
            results.append(backup_service.run_backup_auto(db, root, base="20261102T000000Z"))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    stamps = [item["stamp"] for item in results]
    assert len(set(stamps)) == 4
    for stamp in stamps:
        published = root / stamp
        assert sorted(p.name for p in published.iterdir()) == ["crossproject.db"]
        conn = sqlite3.connect(published / "crossproject.db")
        rows = conn.execute("SELECT name FROM projects").fetchall()
        conn.close()
        assert rows == [("甲项目",)]
