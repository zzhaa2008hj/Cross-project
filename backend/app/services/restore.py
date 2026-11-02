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
    "restore_lock",
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


@contextmanager
def restore_lock(db_path: Path):
    """恢复期间独占库锁：拿不到锁说明应用仍在运行，恢复立即中止。

    锁在整个"生成回滚副本 → 原子替换"过程中保持，避免应用在替换中途启动。
    """
    path = lock_path_for(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "w")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(
                f"应用仍在运行（库锁被占用：{path}），恢复已中止"
            ) from exc
        try:
            yield handle
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()


def _models():
    """延迟导入模型，避免在只需要校验时也拉起整套 ORM。"""
    from .. import models  # noqa: F401  确保模型注册
    from ..db import Base

    return Base


def _required_schema() -> dict[str, set[str]]:
    """表名 → 必须存在的列（当前模型的全部列）。

    候选库必须能承载当前代码的全部字段：缺列的旧库一旦恢复，应用会在读写时
    报错。历史版本的备份改走 JSON 恢复路径（按当前模型重建结构）。
    """
    base = _models()
    required: dict[str, set[str]] = {}
    for table in base.metadata.sorted_tables:
        required[table.name] = {column.name for column in table.columns}
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


def _allocate_rollback_path(db_path: Path, stamp: str) -> Path:
    """分配回滚副本路径；同 stamp 已存在时追加序号，绝不覆盖已有回滚副本。

    与备份版本号的惯例一致（见 ``backup.next_free_stamp``）：回滚副本就是恢复前的
    原始恢复点，覆盖它等于丢掉上一次恢复的依据。CLI 的版本号精确到秒，同一秒内
    重复恢复完全可能发生。
    """
    db_path = Path(db_path)
    candidate = _rollback_path(db_path, stamp)
    for index in range(2, 52):
        if not candidate.exists():
            return candidate
        candidate = db_path.parent / f"{db_path.name}.rollback-{stamp}-{index}"
    raise FileExistsError(
        f"回滚副本序号已用尽，无法保留原始恢复点：{db_path.parent}"
    )


def _clear_sidecars(db_path: Path) -> None:
    """删掉旧库的 WAL 附属文件，避免替换后的库读到旧日志。"""
    for suffix in ("-wal", "-shm"):
        side = Path(str(db_path) + suffix)
        if side.exists():
            side.unlink()


def _publish(new_db: Path, db_path: Path) -> None:
    """把重建好的库原子替换到正式位置。

    候选库可能带着自己的 ``-wal`` 附属：已提交但尚未 checkpoint 的数据就在里面，
    直接复制主文件会把这些已提交事务静默丢掉（校验是只读打开、能看到 WAL 里的新值，
    所以校验通过并不代表复制出来的主文件包含这些数据）。这里先用备份 API 折一份
    自洽快照——它会把源库 WAL 中的已提交内容并入目标文件——再原子替换。
    """
    db_path = Path(db_path)
    new_db = Path(new_db)
    tmp = db_path.parent / f".{db_path.name}.restore-new"
    for stale in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
        if stale.exists():
            stale.unlink()

    snapshot_db(new_db, tmp)
    _clear_sidecars(db_path)
    os.replace(tmp, db_path)
    # 快照目标自身也可能落下附属文件（源库是 WAL 时），替换后要清掉。
    _clear_sidecars(tmp)


def _capture_rollback(db_path: Path, rollback: Path) -> bool:
    """在**已分配好**的路径上生成回滚副本；现库已损坏时保留原始字节，不阻断恢复。

    返回回滚副本是否是有效的 SQLite 快照。调用方必须先用
    ``_allocate_rollback_path`` 拿路径：这里不再删除既有文件，既有回滚副本是
    上一次恢复的依据，不能被静默覆盖。
    """
    try:
        snapshot_db(db_path, rollback)
        return True
    except sqlite3.DatabaseError:
        # 现库本身不是有效 SQLite：把原始字节留作回滚依据，继续恢复。
        shutil.copyfile(db_path, rollback)
        return False


def restore_sqlite(candidate: Path, db_path: Path, stamp: str) -> dict:
    """用一份 SQLite 库恢复现库，保留回滚副本。

    候选库必须先通过校验；不通过则抛 ``ValueError``，现库与回滚副本都不动。
    整个替换过程独占库锁，应用在运行时会直接被拒绝。
    """
    candidate = Path(candidate)
    db_path = Path(db_path)
    problems = validate_sqlite_candidate(candidate)
    if problems:
        raise ValueError("候选库校验未通过：" + "；".join(problems))

    with restore_lock(db_path):
        rollback = _allocate_rollback_path(db_path, stamp)
        rollback_valid = _capture_rollback(db_path, rollback)
        _publish(candidate, db_path)
    return {
        "restored_from": str(candidate),
        "rollback_path": str(rollback),
        "rollback_valid": rollback_valid,
    }


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
    导出必须包含当前模型的全部表，否则拒绝恢复（避免用不完整的导出清空现库）。
    完整但无数据行的导出是合法恢复源（``build_export`` 对全新空库可以正常产出）。
    """
    source = Path(source)
    db_path = Path(db_path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"导出文件无法读取：{exc}") from exc
    if not isinstance(payload, dict) or "tables" not in payload:
        raise ValueError("导出文件缺少 tables 段，不是有效的导出文件")

    base = _models()
    tables = base.metadata.sorted_tables
    exported = payload.get("tables")
    if not isinstance(exported, dict):
        raise ValueError("导出文件的 tables 段不是对象，不是有效的导出文件")
    missing_tables = [table.name for table in tables if table.name not in exported]
    if missing_tables:
        raise ValueError(
            "导出文件缺少必需的表：" + "、".join(missing_tables) + "，拒绝恢复（会清空现库）"
        )
    # 这里刻意不做"至少一行数据"的判断：完整空库是本产品自己能产出的合法状态
    # （新建库备份后立刻恢复即此情形），行数不构成合法性判据。

    with restore_lock(db_path):
        tmp = db_path.parent / f".{db_path.name}.restore-json-{stamp}.tmp"
        for stale in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
            if stale.exists():
                stale.unlink()

        engine = create_engine(f"sqlite:///{tmp}")
        try:
            base.metadata.create_all(bind=engine)
        finally:
            engine.dispose()

        conn = sqlite3.connect(str(tmp))
        try:
            conn.execute("PRAGMA foreign_keys=OFF")
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

        rollback = _allocate_rollback_path(db_path, stamp)
        rollback_valid = _capture_rollback(db_path, rollback)

        _publish(tmp, db_path)
        for stale in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
            if stale.exists():
                stale.unlink()

    return {
        "restored_from": str(source),
        "rollback_path": str(rollback),
        "rollback_valid": rollback_valid,
    }
