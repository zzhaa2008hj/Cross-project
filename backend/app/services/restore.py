"""E4：离线恢复（校验、原子替换、回滚保留）。

两种恢复方式：

* ``restore_sqlite``：直接用一份 SQLite 库文件替换现库，保留结构与约束。
* ``restore_json``：用导出 JSON 的数据重建一个库，结构按当前模型定义生成。

两者都是离线操作：先确认应用已停（文件锁），再校验候选库，校验通过才
原子替换现库，并保留一份回滚副本。失败时现库保持原样。
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine

from .snapshot import snapshot_db

__all__ = [
    "assert_app_stopped",
    "app_lock",
    "lock_path_for",
    "restore_json",
    "restore_sqlite",
    "validate_sqlite_candidate",
]


def lock_path_for(db_path: Path) -> Path:
    """应用运行锁文件：与库同目录、同名加 ``.lock``。"""
    db_path = Path(db_path)
    return db_path.parent / f"{db_path.name}.lock"


@contextmanager
def app_lock(db_path: Path):
    """应用运行期持有库锁；持锁期间恢复操作会被拒绝。"""
    path = lock_path_for(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.write(str(os.getpid()))
        handle.flush()
        yield handle
    finally:
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            handle.close()


def assert_app_stopped(db_path: Path) -> None:
    """确认应用已停：库锁拿不到就说明还有进程在用这个库。"""
    path = lock_path_for(db_path)
    if not path.exists():
        return
    handle = open(path, "w")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(
                f"应用仍在运行（库锁被占用：{path}），恢复已中止"
            ) from exc
        fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()


def _models():
    """延迟导入模型，避免在只需要校验时也拉起整套 ORM。"""
    from .. import models  # noqa: F401  确保模型注册
    from ..db import Base

    return Base


def _required_schema() -> dict[str, set[str]]:
    """表名 → 必须存在的列（NOT NULL 且没有默认值的列）。

    只要求"应用写入时一定提供"的列，避免历史库因为后来新增的可空列被误判。
    """
    base = _models()
    required: dict[str, set[str]] = {}
    for table in base.metadata.sorted_tables:
        cols = {
            column.name
            for column in table.columns
            if not column.nullable
            and column.default is None
            and column.server_default is None
        }
        required[table.name] = cols
    return required


def validate_sqlite_candidate(path: Path) -> list[str]:
    """校验候选库能否用来恢复，返回问题列表（空列表表示通过）。"""
    path = Path(path)
    problems: list[str] = []
    if not path.exists():
        return [f"候选库不存在：{path}"]
    if path.stat().st_size == 0:
        return [f"候选库是空文件：{path}"]

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return [f"候选库无法打开：{exc}"]

    try:
        try:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.DatabaseError as exc:
            return [f"候选库不是有效的 SQLite 文件：{exc}"]
        if [row[0] for row in rows] != ["ok"]:
            problems.append(f"完整性检查未通过：{rows[:3]}")

        try:
            fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
        except sqlite3.DatabaseError:
            fk_rows = []
        if fk_rows:
            problems.append(f"外键约束不成立，共 {len(fk_rows)} 处")

        present = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()

    for table, columns in _required_schema().items():
        if table not in present:
            problems.append(f"缺少必需表：{table}")
            continue
        missing = sorted(columns - _columns_of_db(path, table))
        if missing:
            problems.append(f"表 {table} 缺少必需列：{'、'.join(missing)}")
    return problems


def _columns_of_db(path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        return {row[1] for row in rows}
    except sqlite3.DatabaseError:
        return set()
    finally:
        conn.close()


def _rollback_path(db_path: Path, stamp: str) -> Path:
    db_path = Path(db_path)
    return db_path.parent / f"{db_path.name}.rollback-{stamp}"


def _clear_sidecars(db_path: Path) -> None:
    """删掉旧库的 WAL 附属文件，避免替换后的库读到旧日志。"""
    for suffix in ("-wal", "-shm"):
        side = Path(str(db_path) + suffix)
        if side.exists():
            side.unlink()


def _publish(new_db: Path, db_path: Path) -> None:
    """把重建好的库原子替换到正式位置。"""
    db_path = Path(db_path)
    tmp = db_path.parent / f".{db_path.name}.restore-new"
    shutil.copyfile(new_db, tmp)
    _clear_sidecars(db_path)
    os.replace(tmp, db_path)


def restore_sqlite(candidate: Path, db_path: Path, stamp: str) -> dict:
    """用一份 SQLite 库恢复现库，保留回滚副本。

    候选库必须先通过校验；不通过则抛 ``ValueError``，现库与回滚副本都不动。
    """
    candidate = Path(candidate)
    db_path = Path(db_path)
    problems = validate_sqlite_candidate(candidate)
    if problems:
        raise ValueError("候选库校验未通过：" + "；".join(problems))

    assert_app_stopped(db_path)

    rollback = _rollback_path(db_path, stamp)
    if rollback.exists():
        rollback.unlink()
    snapshot_db(db_path, rollback)

    _publish(candidate, db_path)
    return {"restored_from": str(candidate), "rollback_path": str(rollback)}


def _insert_rows(conn: sqlite3.Connection, table, rows: list[dict]) -> int:
    if not rows:
        return 0
    names = [column.name for column in table.columns]
    used = [name for name in names if any(name in row for row in rows)]
    if not used:
        return 0
    placeholders = ", ".join("?" for _ in used)
    columns = ", ".join(f'"{name}"' for name in used)
    payload = [tuple(row.get(name) for name in used) for row in rows]
    conn.executemany(
        f'INSERT INTO "{table.name}" ({columns}) VALUES ({placeholders})', payload
    )
    return len(payload)


def restore_json(source: Path, db_path: Path, stamp: str) -> dict:
    """用导出 JSON 重建现库，保留回滚副本。

    结构按当前模型定义生成（唯一约束、外键都在），数据来自导出文件。
    导出里出现但模型里没有的表会被跳过——记为已知限制。
    """
    source = Path(source)
    db_path = Path(db_path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"导出文件无法读取：{exc}") from exc
    if not isinstance(payload, dict) or "tables" not in payload:
        raise ValueError("导出文件缺少 tables 段，不是有效的导出文件")

    assert_app_stopped(db_path)

    base = _models()
    tmp = db_path.parent / f".{db_path.name}.restore-json-{stamp}.tmp"
    for stale in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
        if stale.exists():
            stale.unlink()

    tables = base.metadata.sorted_tables
    engine = create_engine(f"sqlite:///{tmp}")
    try:
        base.metadata.create_all(bind=engine)
    finally:
        engine.dispose()

    conn = sqlite3.connect(str(tmp))
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        exported = payload.get("tables") or {}
        for table in tables:
            rows = exported.get(table.name) or []
            _insert_rows(conn, table, rows)
        conn.commit()
        problems = validate_sqlite_candidate(tmp)
    finally:
        conn.close()

    if problems:
        for stale in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
            if stale.exists():
                stale.unlink()
        raise ValueError("重建后的库校验未通过：" + "；".join(problems))

    rollback = _rollback_path(db_path, stamp)
    if rollback.exists():
        rollback.unlink()
    snapshot_db(db_path, rollback)

    _publish(tmp, db_path)
    for stale in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
        if stale.exists():
            stale.unlink()

    return {"restored_from": str(source), "rollback_path": str(rollback)}
