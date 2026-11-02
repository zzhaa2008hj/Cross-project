"""E4 Task 4：离线恢复（校验、原子替换、回滚保留）与 CLI。"""
import json
import os
import shutil
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
from app.models import Allocation, Milestone, Person, Project, WeekCapacity
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


def _make_empty_db(path: Path) -> Path:
    """用真实模型 schema 建一个不含任何数据行的库。"""
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    return path


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


def test_restore_json_accepts_complete_empty_export(tmp_path):
    """本产品自己生成的完整空库导出是合法恢复源：合法空值，不是坏输入。

    ``build_export`` 对完整空库能正常产出（各表 0 行），空库备份因此是合法恢复源；
    拒绝它会让「全新库备份 → 恢复」这条正常路径走不通。
    """
    live = _make_db(tmp_path / "live.db", name="现库")
    export = build_export(_make_empty_db(tmp_path / "empty.db"))
    source = tmp_path / "export.json"
    source.write_text(
        json.dumps(export, ensure_ascii=False, default=str), encoding="utf-8"
    )

    result = restore_json(source, live, stamp="20261102T000000Z")

    assert _dump(live) == []
    rollback = Path(result["rollback_path"])
    assert rollback.exists()
    assert _dump(rollback) == [(1, "现库", "active")]


def test_restore_json_rejects_export_missing_model_tables(tmp_path):
    """导出缺少模型表（不完整导出）必须拒绝，不能用空表重建现库。"""
    live = _make_db(tmp_path / "live.db", name="现库")
    payload = {"schema_version": 1, "tables": {"projects": []}}
    source = tmp_path / "export.json"
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError):
        restore_json(source, live, stamp="20261102T000000Z")

    assert _dump(live) == [(1, "现库", "active")]


def _tables_of(export: dict) -> dict:
    """取出导出的全部表值（表名 → 行列表），便于逐表破坏后复用。"""
    return {name: list(rows) for name, rows in export["tables"].items()}


def _source_with_tables(tmp_path: Path, tables: dict, name: str) -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps({"schema_version": 1, "tables": tables}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _empty_source_tables(tmp_path: Path) -> dict:
    """复现 CTO 的复现路径：导出取自**完整空库**（各表本来就是 ``[]``）。

    这正是"非法输入仍报成功"的现场：各表无行可拦，表值一旦被吞成空列表就重建出
    一个空库、覆盖有数据的现库。若用有数据的导出来测，残留的外键引用会先被
    ``validate_sqlite_candidate`` 拦下，测不到这个缺陷。
    """
    return _tables_of(build_export(_make_empty_db(tmp_path / "empty.db")))


def test_restore_json_rejects_table_value_that_is_not_a_list(tmp_path):
    """表值必须是数组：false/null/0/空串/对象都不能被当成"空数据"。

    ``rows = exported.get(name) or []`` 曾把这些错误类型吞成空列表，于是非法导出
    被当成"完整空库"接受并清空有数据的现库。
    """
    live = _make_db(tmp_path / "live.db", name="现库")
    tables = _empty_source_tables(tmp_path)
    for index, bad_value in enumerate((False, None, 0, "", {}, "项目", 3.5)):
        broken = dict(tables)
        broken["projects"] = bad_value
        source = _source_with_tables(tmp_path, broken, f"not-a-list-{index}.json")

        with pytest.raises(ValueError, match="projects"):
            restore_json(source, live, stamp=f"20261102T1000{index}Z")

        assert _dump(live) == [(1, "现库", "active")]


def test_restore_json_rejects_export_where_every_table_value_is_false_or_null(
    tmp_path,
):
    """CTO 复现例：所有表值改成 false（或 null），恢复不得报成功、现库不得被清空。"""
    live = _make_db(tmp_path / "live.db", name="现库")
    tables = _empty_source_tables(tmp_path)
    for index, bad_value in enumerate((False, None)):
        broken = {name: bad_value for name in tables}
        source = _source_with_tables(tmp_path, broken, f"all-{index}.json")

        with pytest.raises(ValueError):
            restore_json(source, live, stamp=f"20261102T1006{index}Z")

        assert _dump(live) == [(1, "现库", "active")]


def test_restore_json_rejects_row_that_is_not_an_object(tmp_path):
    """每行必须是对象：非对象行不得被静默跳过或当成空行插入。"""
    live = _make_db(tmp_path / "live.db", name="现库")
    tables = _empty_source_tables(tmp_path)
    for index, bad_rows in enumerate(([None], ["项目"], [1], [[]], [{"id": 1}, "项目"])):
        broken = dict(tables)
        broken["projects"] = bad_rows
        source = _source_with_tables(tmp_path, broken, f"not-an-object-{index}.json")

        with pytest.raises(ValueError, match="projects"):
            restore_json(source, live, stamp=f"20261102T1001{index}Z")

        assert _dump(live) == [(1, "现库", "active")]


def test_restore_json_rejects_row_missing_required_fields(tmp_path):
    """行必须带齐模型约束要求的必需字段（非空列，含主键）。

    ``projects=[{}]`` 这类行没有可识别的必需字段，过去被 ``_insert_rows`` 静默
    跳过（``used`` 为空 → 返回 0 行），恢复照样报成功。
    """
    live = _make_db(tmp_path / "live.db", name="现库")
    tables = _empty_source_tables(tmp_path)
    incomplete_rows = (
        [{}],
        [{"id": 1}],
        [{"name": "甲"}],
        [{"id": 1, "name": "甲", "state": None}],
        [{"note": "只有可选列"}],
        [{"id": 1, "name": "甲", "不存在的列": 1}],
    )
    for index, bad_rows in enumerate(incomplete_rows):
        broken = dict(tables)
        broken["projects"] = bad_rows
        source = _source_with_tables(tmp_path, broken, f"required-{index}.json")

        with pytest.raises(ValueError, match="projects"):
            restore_json(source, live, stamp=f"20261102T1002{index}Z")

        assert _dump(live) == [(1, "现库", "active")]


def test_restore_json_rejects_unknown_schema_version(tmp_path):
    """schema_version 与当前恢复端不一致时拒绝，避免跨版本结构被当成同一份数据。"""
    live = _make_db(tmp_path / "live.db", name="现库")
    export = build_export(live)
    export["schema_version"] = 99
    source = tmp_path / "future.json"
    source.write_text(
        json.dumps(export, ensure_ascii=False, default=str), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="schema_version"):
        restore_json(source, live, stamp="20261102T100300Z")

    assert _dump(live) == [(1, "现库", "active")]


def test_restore_json_accepts_null_zero_and_empty_tables(tmp_path):
    """守护用例：合法空库、列内 NULL/0/空串/False 必须继续被接受。

    与上面几条互为边界——校验只拒绝"结构非法"，不恢复"至少一行"的旧门槛，
    也不把合法的 NULL/0 误判成缺失。
    """
    live = _make_db(tmp_path / "live.db", name="现库")
    source_db = _make_db(tmp_path / "source.db", name="源库")
    engine = create_engine(f"sqlite:///{source_db}")
    with Session(engine) as session:
        session.add(
            Project(id=2, name="零投入", state="active", priority="", archived=False)
        )
        session.add(
            Allocation(
                id=1, person_id=7, project_id=1, week=date(2026, 11, 3), days=0
            )
        )
        session.add(
            Allocation(
                id=2, person_id=7, project_id=1, week=date(2026, 11, 4), days=0.5
            )
        )
        session.commit()
    engine.dispose()

    export = build_export(source_db)
    assert export["tables"]["reschedule_previews"] == []  # 合法完整空库
    target = tmp_path / "export.json"
    target.write_text(
        json.dumps(export, ensure_ascii=False, default=str), encoding="utf-8"
    )

    restore_json(target, live, stamp="20261102T100400Z")

    assert _dump(live) == [(1, "源库", "active"), (2, "零投入", "active")]
    conn = sqlite3.connect(str(live))
    days = conn.execute("SELECT days FROM allocations ORDER BY id").fetchall()
    caps = conn.execute("SELECT id, days FROM week_capacities ORDER BY id").fetchall()
    conn.close()
    assert days == [(0.0,), (0.5,)]  # 0 是合法值，不能被当成缺失
    assert caps == [(1, None)]  # nullable 列的 NULL 原样保留


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


def test_restore_json_repeats_same_stamp_keeps_earlier_rollback(tmp_path):
    """JSON 恢复路径同样不得用同一 stamp 覆盖上一份回滚副本。"""
    live = _make_db(tmp_path / "live.db", name="现库")
    export = build_export(live)
    source = tmp_path / "export.json"
    source.write_text(
        json.dumps(export, ensure_ascii=False, default=str), encoding="utf-8"
    )

    first = restore_json(source, live, stamp="20261102T000000Z")
    first_rollback = Path(first["rollback_path"])
    assert _dump(first_rollback) == [(1, "现库", "active")]

    second = restore_json(source, live, stamp="20261102T000000Z")

    assert _dump(first_rollback) == [(1, "现库", "active")]
    assert Path(second["rollback_path"]) != first_rollback
    assert _dump(Path(second["rollback_path"])) == [(1, "现库", "active")]
