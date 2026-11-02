"""E4：一致性快照与导出数据读取。

快照用 SQLite backup API 在线捕获，即使有并发写入也只得到"事务边界完整"的库；
导出所需的全表数据统一从快照读，保证 JSON / Markdown / Obsidian 摘要三者一致。
"""
from __future__ import annotations

import base64
import sqlite3
from pathlib import Path

__all__ = ["snapshot_db", "read_tables", "table_columns", "list_tables"]


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _json_safe(value):
    """把 SQLite 取出的值转成 JSON 安全值；二进制走 base64 文本。"""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode("ascii")
    return value


def list_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


def _columns_of(conn: sqlite3.Connection, table: str) -> list[dict]:
    info = conn.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
    return [
        {
            "name": row[1],
            "type": row[2],
            "notnull": bool(row[3]),
            "default": row[4],
            "pk": int(row[5]),
        }
        for row in info
    ]


def table_columns(db_path: Path) -> dict[str, list[dict]]:
    """返回 表名 → 列信息（列名、类型、是否主键）。"""
    conn = sqlite3.connect(str(db_path))
    try:
        return {table: _columns_of(conn, table) for table in list_tables(conn)}
    finally:
        conn.close()


def read_tables(db_path: Path) -> dict[str, list[dict]]:
    """读出全部业务表的全部行，按列顺序转成 dict 列表。"""
    conn = sqlite3.connect(str(db_path))
    try:
        result: dict[str, list[dict]] = {}
        for table in list_tables(conn):
            columns = _columns_of(conn, table)
            if not columns:
                result[table] = []
                continue
            names = [c["name"] for c in columns]
            projection = ", ".join(_quote(n) for n in names)
            rows = conn.execute(
                f"SELECT {projection} FROM {_quote(table)}"
            ).fetchall()
            result[table] = [
                {name: _json_safe(value) for name, value in zip(names, row)}
                for row in rows
            ]
        return result
    finally:
        conn.close()


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


def foreign_keys(db_path: Path) -> dict[str, list[dict]]:
    """返回 表名 → 外键列表（引用表、引用列、本表列）。

    恢复时据此决定建表顺序与外键约束，保证重建出来的库仍然自洽。
    """
    conn = sqlite3.connect(str(db_path))
    try:
        result: dict[str, list[dict]] = {}
        for table in list_tables(conn):
            rows = conn.execute(
                f"PRAGMA foreign_key_list({_quote(table)})"
            ).fetchall()
            grouped: dict[int, dict] = {}
            for row in rows:
                fk_id, _seq, ref_table, from_col, to_col = row[0], row[1], row[2], row[3], row[4]
                entry = grouped.setdefault(
                    fk_id,
                    {
                        "referred_table": ref_table,
                        "referred_columns": [],
                        "columns": [],
                    },
                )
                entry["referred_columns"].append(to_col)
                entry["columns"].append(from_col)
            if grouped:
                result[table] = [grouped[key] for key in sorted(grouped)]
        return result
    finally:
        conn.close()
