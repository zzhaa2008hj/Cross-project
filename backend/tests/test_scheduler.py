"""E4 Task 5：每日备份调度。"""
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Person
from app.services.scheduler import (
    backup_enabled,
    backup_interval_seconds,
    run_scheduled_backup,
)


def _make_data_dir(tmp_path: Path) -> Path:
    """在临时数据目录里建一个真实可快照的库。"""
    data_dir = tmp_path / "data"
    db_file = data_dir / "sqlite" / "crossproject.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        session.add(Person(id=1, name="张三"))
        session.commit()
    engine.dispose()
    return data_dir


def test_backup_enabled_defaults_to_true(monkeypatch):
    monkeypatch.delenv("CP_BACKUP_ENABLED", raising=False)
    assert backup_enabled() is True


def test_backup_enabled_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("CP_BACKUP_ENABLED", "0")
    assert backup_enabled() is False


def test_backup_interval_defaults_to_24_hours(monkeypatch):
    monkeypatch.delenv("CP_BACKUP_INTERVAL_HOURS", raising=False)
    assert backup_interval_seconds() == 24 * 3600


def test_backup_interval_reads_env(monkeypatch):
    monkeypatch.setenv("CP_BACKUP_INTERVAL_HOURS", "1")
    assert backup_interval_seconds() == 3600


def test_run_scheduled_backup_publishes_backup(tmp_path, monkeypatch):
    data_dir = _make_data_dir(tmp_path)
    monkeypatch.setenv("CP_DATA_DIR", str(data_dir))
    backups = tmp_path / "backups"
    monkeypatch.setenv("CP_BACKUP_DIR", str(backups))

    summary = run_scheduled_backup()

    assert summary is not None
    assert summary["stamp"]
    assert (backups / summary["stamp"] / "export.json").exists()


def test_run_scheduled_backup_swallows_failure(tmp_path, monkeypatch):
    """备份失败只记录日志，不应把服务带崩。"""
    data_dir = _make_data_dir(tmp_path)
    monkeypatch.setenv("CP_DATA_DIR", str(data_dir))
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("占位", encoding="utf-8")
    monkeypatch.setenv("CP_BACKUP_DIR", str(blocker / "backups"))

    assert run_scheduled_backup() is None
