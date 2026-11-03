"""E4：一致性快照。

快照用 SQLite backup API 在线捕获，即使有并发写入也只得到"事务边界完整"的库；
备份与恢复都基于它，保证产物自洽。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

__all__ = ["snapshot_db"]


def snapshot_db(db_path: Path, dest: Path) -> Path:
    """把 ``db_path`` 一致性复制到 ``dest``，返回 dest。

    目标已存在时抛 ``FileExistsError``——快照是证据，不允许被静默覆盖。
    """
    db_path = Path(db_path)
    dest = Path(dest)
    if dest.exists():
        raise FileExistsError(f"快照目标已存在，拒绝覆盖：{dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    source = sqlite3.connect(str(db_path))
    try:
        target = sqlite3.connect(str(dest))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    return dest
