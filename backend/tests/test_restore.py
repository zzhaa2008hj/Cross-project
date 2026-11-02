"""E4 Task 4：离线恢复（校验、原子替换、回滚保留）与 CLI。"""
import json
import os
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Milestone, Person, Project, WeekCapacity
from app.services.export import build_export
from app.services.restore import (
    assert_app_stopped,
    restore_json,
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


def test_restore_json_rebuilds_equivalent_db(tmp_path):
    live = _make_db(tmp_path / "live.db", name="现库")
    export = build_export(live)
    json_path = tmp_path / "export.json"
    json_path.write_text(
        json.dumps(export, ensure_ascii=False, default=str), encoding="utf-8"
    )

    result = restore_json(json_path, live, stamp="20261102T000000Z")

    assert _dump(live) == [(1, "现库", "active")]
    conn = sqlite3.connect(str(live))
    caps = conn.execute("SELECT days FROM week_capacities").fetchall()
    conn.close()
    assert caps == [(None,)]
    assert Path(result["rollback_path"]).exists()


def test_restore_json_with_bad_payload_leaves_original(tmp_path):
    live = _make_db(tmp_path / "live.db", name="现库")
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema_version": 1}', encoding="utf-8")

    with pytest.raises(ValueError):
        restore_json(bad, live, stamp="20261102T000000Z")

    assert _dump(live) == [(1, "现库", "active")]


def test_restore_json_preserves_unique_constraint(tmp_path):
    """重建库要保留唯一约束，否则恢复后可以写入重复人员名。"""
    live = _make_db(tmp_path / "live.db", name="现库")
    export = build_export(live)
    json_path = tmp_path / "export.json"
    json_path.write_text(
        json.dumps(export, ensure_ascii=False, default=str), encoding="utf-8"
    )

    restore_json(json_path, live, stamp="20261102T000000Z")

    engine = create_engine(f"sqlite:///{live}")
    with Session(engine) as session:
        session.add(Person(id=99, name="张三"))
        with pytest.raises(IntegrityError):
            session.flush()
    engine.dispose()


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


def test_cli_backup_then_restore_json(tmp_path):
    db = _make_db(tmp_path / "live.db", name="现库")
    backups = tmp_path / "backups"

    made = _run_cli("backup", "--db", str(db), "--backup-dir", str(backups))
    assert made.returncode == 0, made.stderr
    published = sorted(p for p in backups.iterdir() if p.is_dir())
    assert len(published) == 1

    restored = _run_cli(
        "restore",
        "--source",
        str(published[0] / "export.json"),
        "--db",
        str(db),
        "--type",
        "json",
    )
    assert restored.returncode == 0, restored.stderr
    assert _dump(db) == [(1, "现库", "active")]


def test_cli_restore_reports_failure_with_nonzero_exit(tmp_path):
    db = _make_db(tmp_path / "live.db", name="现库")
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")

    result = _run_cli(
        "restore", "--source", str(bad), "--db", str(db), "--type", "json"
    )

    assert result.returncode != 0
    assert result.stderr.strip()
