"""E4 Task 4：离线恢复（校验、原子替换、回滚保留）与 CLI。"""
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Milestone, Person, Project, WeekCapacity
from app.services.restore import (
    assert_app_stopped,
    restore_sqlite,
    validate_sqlite_candidate,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _make_db(path: Path, name: str = "甲项目") -> Path:
    """用真实模型 schema 建库并塞最小数据。"""
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        person = Person(id=7, name="张三")
        session.add(person)
        project = Project(id=1, name=name, state="active")
        session.add(project)
        session.add(Milestone(id=1, project_id=1, name="节点A", state="进行中"))
        session.add(
            WeekCapacity(id=1, person_id=7, week=date(2026, 11, 2), days=None)
        )
        session.commit()
    engine.dispose()
    return path


def _dump(path: Path) -> list[tuple]:
    conn = sqlite3.connect(str(path))
    rows = conn.execute("SELECT id,name,state FROM projects ORDER BY id").fetchall()
    conn.close()
    return rows


def _read_main_file_only(path: Path) -> list[tuple]:
    """只读 ``.db`` 主文件、不带上 ``-wal`` 附属，用来观测 checkpoint 状态。"""
    tmp = path.parent / ".__main_only.db"
    for stale in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
        if stale.exists():
            stale.unlink()
    shutil.copyfile(path, tmp)
    try:
        return _dump(tmp)
    finally:
        tmp.unlink()


def test_validate_sqlite_candidate_accepts_good_db(tmp_path):
    assert validate_sqlite_candidate(_make_db(tmp_path / "good.db")) == []


def test_validate_sqlite_candidate_rejects_broken_file(tmp_path):
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"not a sqlite database at all")
    problems = validate_sqlite_candidate(broken)
    assert problems


def test_validate_sqlite_candidate_rejects_missing_tables(tmp_path):
    path = tmp_path / "partial.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    problems = validate_sqlite_candidate(path)
    assert any("projects" in p for p in problems)


def test_restore_sqlite_replaces_db_and_keeps_rollback(tmp_path):
    live = _make_db(tmp_path / "live.db", name="现库")
    candidate = _make_db(tmp_path / "candidate.db", name="备份库")

    result = restore_sqlite(candidate, live, stamp="20261102T000000Z")

    assert _dump(live) == [(1, "备份库", "active")]
    rollback = Path(result["rollback_path"])
    assert rollback.exists()
    assert _dump(rollback) == [(1, "现库", "active")]
    assert result["restored_from"] == str(candidate)


def test_restore_sqlite_with_invalid_candidate_leaves_original(tmp_path):
    live = _make_db(tmp_path / "live.db", name="现库")
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"garbage")

    with pytest.raises(ValueError):
        restore_sqlite(broken, live, stamp="20261102T000000Z")

    assert _dump(live) == [(1, "现库", "active")]
    assert not (tmp_path / "live.db.rollback-20261102T000000Z").exists()


def test_assert_app_stopped_fails_while_lock_held(tmp_path):
    import fcntl

    db = tmp_path / "live.db"
    _make_db(db)
    lock_path = Path(str(db) + ".lock")
    handle = open(lock_path, "w")
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(RuntimeError):
            assert_app_stopped(db)
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()

    assert_app_stopped(db)


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BACKEND_DIR)
    return subprocess.run(
        [sys.executable, "-m", "app.backup_cli", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(BACKEND_DIR),
    )


def test_cli_backup_then_restore_sqlite(tmp_path):
    db = _make_db(tmp_path / "live.db", name="现库")
    backups = tmp_path / "backups"

    made = _run_cli("backup", "--db", str(db), "--backup-dir", str(backups))
    assert made.returncode == 0, made.stderr
    published = sorted(p for p in backups.iterdir() if p.is_dir())
    assert len(published) == 1

    restored = _run_cli(
        "restore",
        "--source",
        str(published[0] / "crossproject.db"),
        "--db",
        str(db),
    )
    assert restored.returncode == 0, restored.stderr
    assert _dump(db) == [(1, "现库", "active")]


def test_cli_restore_reports_failure_with_nonzero_exit(tmp_path):
    db = _make_db(tmp_path / "live.db", name="现库")
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a sqlite database")

    result = _run_cli("restore", "--source", str(bad), "--db", str(db))

    assert result.returncode != 0
    assert result.stderr.strip()


def test_validate_sqlite_candidate_rejects_missing_model_columns(tmp_path):
    """缺列的候选库（如旧版本备份）必须被拒绝：应用按当前模型查询会直接报错。"""
    path = _make_db(tmp_path / "old.db")
    conn = sqlite3.connect(str(path))
    conn.execute("ALTER TABLE projects DROP COLUMN state")
    conn.commit()
    conn.close()

    problems = validate_sqlite_candidate(path)

    assert any("state" in problem for problem in problems)


def test_restore_holds_db_lock_throughout_replacement(tmp_path, monkeypatch):
    """恢复全程独占库锁：替换过程中应用不得启动、另一个恢复也不得并发进入。"""
    import fcntl

    from app.services import restore as restore_service

    live = _make_db(tmp_path / "live.db", name="现库")
    candidate = _make_db(tmp_path / "candidate.db", name="备份库")
    original = restore_service.snapshot_db
    observed: dict[str, bool] = {}

    def probing_snapshot(source, dest):
        result = original(source, dest)
        # 恢复全程持有现库的库锁：持锁窗口内的两次快照（生成回滚副本、折发布快照）
        # 都应看到现库的锁仍被占住。探针锚在现库上而不是 source 上——发布用的
        # 快照源是候选库，它的锁本来就不属于这次恢复。
        handle = open(restore_service.lock_path_for(live), "w")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            observed["lock_available"] = True
            fcntl.flock(handle, fcntl.LOCK_UN)
        except OSError:
            observed["lock_available"] = False
        finally:
            handle.close()
        return result

    monkeypatch.setattr(restore_service, "snapshot_db", probing_snapshot)

    restore_sqlite(candidate, live, stamp="20261102T000000Z")

    assert observed["lock_available"] is False


def test_restore_sqlite_succeeds_when_live_db_is_corrupt(tmp_path):
    """现库损坏时，有效备份仍应能恢复；损坏原文件保留为回退副本。"""
    live = tmp_path / "live.db"
    live.write_bytes(b"this is definitely not a sqlite database")
    candidate = _make_db(tmp_path / "candidate.db", name="备份库")

    result = restore_sqlite(candidate, live, stamp="20261102T000000Z")

    assert _dump(live) == [(1, "备份库", "active")]
    rollback = Path(result["rollback_path"])
    assert rollback.exists()
    assert rollback.read_bytes() == b"this is definitely not a sqlite database"


def test_restore_sqlite_publishes_committed_wal_content(tmp_path):
    """候选库已提交的数据只落在 -wal：校验读到新值，恢复结果也必须是新值。

    旧实现只复制候选库主文件、随后删掉附属文件，已提交事务被静默丢弃：
    校验通过且看到新值，恢复出来却是旧 checkpoint 值。
    """
    live = _make_db(tmp_path / "live.db", name="现库")
    candidate = _make_db(tmp_path / "candidate.db", name="备份库")

    keeper = sqlite3.connect(str(candidate))
    keeper.execute("PRAGMA journal_mode=WAL")
    keeper.execute("PRAGMA wal_autocheckpoint=0")
    keeper.execute("BEGIN")
    # 必须真正读一次，快照才占住；否则 keeper 不持锁，writer 关闭时被动
    # checkpoint 会把 WAL 折回主文件，测不出「主文件旧 / -wal 新」这一形态。
    keeper.execute("SELECT * FROM projects").fetchall()
    try:
        writer = sqlite3.connect(str(candidate))
        writer.execute("UPDATE projects SET name=? WHERE id=1", ("备份库-新名",))
        writer.commit()
        writer.close()

        # 主文件停在旧值，已提交的新值只存在于 -wal
        assert _read_main_file_only(candidate) == [(1, "备份库", "active")]
        assert _dump(candidate) == [(1, "备份库-新名", "active")]
        assert validate_sqlite_candidate(candidate) == []

        restore_sqlite(candidate, live, stamp="20261102T000000Z")

        assert _dump(live) == [(1, "备份库-新名", "active")]
    finally:
        keeper.close()


def test_restore_sqlite_repeats_same_stamp_keeps_earlier_rollback(tmp_path):
    """同一 stamp 二次恢复不得覆盖第一次的回滚副本：原始恢复点必须保留。"""
    live = _make_db(tmp_path / "live.db", name="现库")
    candidate = _make_db(tmp_path / "candidate.db", name="备份库")

    first = restore_sqlite(candidate, live, stamp="20261102T000000Z")
    first_rollback = Path(first["rollback_path"])
    assert _dump(first_rollback) == [(1, "现库", "active")]

    second = restore_sqlite(candidate, live, stamp="20261102T000000Z")

    assert _dump(first_rollback) == [(1, "现库", "active")]
    assert Path(second["rollback_path"]) != first_rollback
    assert _dump(Path(second["rollback_path"])) == [(1, "备份库", "active")]
