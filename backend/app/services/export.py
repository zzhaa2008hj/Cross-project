"""E4：导出产物（JSON / Markdown / Obsidian 摘要）与预览差异。

三种产物都从同一份一致性快照读出，保证彼此一致；`diff_exports` 按主键比较两次
导出，用于预览页展示"这次相对上次变了什么"。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .snapshot import foreign_keys, read_tables, table_columns

__all__ = [
    "build_export",
    "render_markdown",
    "render_obsidian_summary",
    "diff_exports",
]

SCHEMA_VERSION = 1
NULL_MARKER = "_NULL_"
_MAX_IDS = 50


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _content_hash(tables: dict) -> str:
    payload = json.dumps(tables, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]


def _snapshot_id(tables: dict) -> str:
    """快照标识：``snap-<UTC 时间戳>-<内容 sha256 前 8 位>``。

    时间戳让每次预览有唯一编号；内容散列让"内容相同的两次导出"可以被识别出来。
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"snap-{stamp}-{_content_hash(tables)}"


def build_export(db_path: Path) -> dict:
    """从给定（通常是一致性快照的）数据库路径构建导出结构。

    ``db_path`` 必须是调用方已经捕获的一致性快照或静止的库文件，本函数本身不做快照。
    """
    tables = read_tables(Path(db_path))
    columns = table_columns(Path(db_path))
    fks = foreign_keys(Path(db_path))
    counts = {name: len(rows) for name, rows in tables.items()}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "snapshot_id": _snapshot_id(tables),
        "counts": counts,
        "columns": columns,
        "foreign_keys": fks,
        "tables": tables,
    }


def _cell(value) -> str:
    if value is None:
        return NULL_MARKER
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _md_escape(value: str) -> str:
    return value.replace("|", "\\|")


def render_markdown(export: dict) -> str:
    """把导出渲染成人类可读的 Markdown（全表）。"""
    tables = export.get("tables", {})
    columns = export.get("columns", {})
    counts = export.get("counts", {})

    lines = [
        "# 跨项目管理软件导出",
        "",
        f"- 生成时间：{export.get('generated_at', '')}",
        f"- 快照版本：{export.get('snapshot_id', '')}",
        f"- 表数量：{len(tables)}",
        "",
        "> 本文件由软件导出，只读快照内容，不写回 vault 笔记或脚本。",
        "",
    ]
    for name in sorted(tables):
        rows = tables[name]
        cols = [c["name"] for c in columns.get(name, [])]
        if not cols and rows:
            cols = list(rows[0].keys())
        lines.append(f"## {name}（{counts.get(name, len(rows))} 行）")
        lines.append("")
        if not cols:
            lines.append("_无字段_")
            lines.append("")
            continue
        lines.append("| " + " | ".join(_md_escape(c) for c in cols) + " |")
        lines.append("| " + " | ".join("---" for _ in cols) + " |")
        for row in rows:
            lines.append(
                "| " + " | ".join(_md_escape(_cell(row.get(c))) for c in cols) + " |"
            )
        lines.append("")
    return "\n".join(lines)


def _rows(export: dict, table: str) -> list[dict]:
    return (export.get("tables") or {}).get(table) or []


def _summary_value(row: dict, key: str, default: str = "") -> str:
    value = row.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def render_obsidian_summary(export: dict) -> str:
    """渲染紧凑 Obsidian 摘要（供人工阅读，不写回 vault）。"""
    counts = export.get("counts", {})
    lines = [
        "# 跨项目管理软件摘要",
        "",
        f"- 生成时间：{export.get('generated_at', '')}",
        f"- 快照版本：{export.get('snapshot_id', '')}",
        "",
        "> 本摘要只读取软件数据库，不写回 vault 笔记或脚本。",
        "",
        "## 项目",
        "",
    ]
    projects = _rows(export, "projects")
    if projects:
        lines.append("| 项目 | 状态 | 进度 |")
        lines.append("| --- | --- | --- |")
        for row in projects:
            progress = row.get("progress")
            progress_text = "未知" if progress is None else str(progress)
            lines.append(
                f"| {_summary_value(row, 'name', '(未命名)')} "
                f"| {_summary_value(row, 'state', '未知')} "
                f"| {progress_text} |"
            )
    else:
        lines.append("_暂无项目_")
    lines.append("")

    lines.append("## 节点状态分布")
    lines.append("")
    milestones = _rows(export, "milestones")
    if milestones:
        distribution: dict[str, int] = {}
        for row in milestones:
            state = _summary_value(row, "state", "未知")
            distribution[state] = distribution.get(state, 0) + 1
        for state in sorted(distribution):
            lines.append(f"- {state}：{distribution[state]} 个")
    else:
        lines.append("_暂无节点_")
    lines.append("")

    lines.append("## 人员容量")
    lines.append("")
    capacities = _rows(export, "week_capacities")
    if capacities:
        lines.append("| 周次 | 人员 | 天数 |")
        lines.append("| --- | --- | --- |")
        for row in capacities:
            days = row.get("days")
            days_text = "未知" if days is None else str(days)
            lines.append(
                f"| {_summary_value(row, 'week', '未知')} "
                f"| {_summary_value(row, 'person_id', '未知')} "
                f"| {days_text} |"
            )
    else:
        lines.append("_暂无容量记录_")
    lines.append("")

    lines.append("## 最近历史")
    lines.append("")
    history = _rows(export, "history_entries")
    if history:
        recent = history[-10:]
        for row in recent:
            lines.append(
                f"- {_summary_value(row, 'created_at', '')} "
                f"{_summary_value(row, 'action', '变更')} "
                f"{_summary_value(row, 'entity_name', '')}"
            )
    else:
        lines.append("_暂无历史_")
    lines.append("")

    lines.append("## 表行数")
    lines.append("")
    for name in sorted(counts):
        lines.append(f"- {name}：{counts[name]}")
    lines.append("")
    return "\n".join(lines)


def _primary_key_columns(export: dict, table: str) -> list[str]:
    cols = (export.get("columns") or {}).get(table) or []
    return [c["name"] for c in cols if c.get("pk")]


def _row_key(export: dict, table: str, row: dict) -> str:
    pk_columns = _primary_key_columns(export, table)
    if pk_columns:
        return "|".join(_cell(row.get(c)) for c in pk_columns)
    return json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)


def diff_exports(prev: dict | None, cur: dict) -> dict:
    """比较两次导出，返回按表统计的新增/删除/修改行。

    ``prev`` 为 ``None`` 表示这是第一次预览，全部行记作新增。
    """
    cur_tables = cur.get("tables") or {}
    tables: dict[str, dict] = {}

    if prev is None:
        for name, rows in cur_tables.items():
            ids = [_row_key(cur, name, row) for row in rows]
            tables[name] = {
                "added": len(rows),
                "removed": 0,
                "changed": 0,
                "ids": ids[:_MAX_IDS],
            }
        return {"is_first": True, "tables": tables}

    prev_tables = prev.get("tables") or {}
    for name in sorted(set(prev_tables) | set(cur_tables)):
        prev_map = {
            _row_key(cur, name, row): row for row in prev_tables.get(name) or []
        }
        cur_map = {_row_key(cur, name, row): row for row in cur_tables.get(name) or []}
        added = [key for key in cur_map if key not in prev_map]
        removed = [key for key in prev_map if key not in cur_map]
        changed = [
            key for key in cur_map
            if key in prev_map and prev_map[key] != cur_map[key]
        ]
        ids = (added + removed + changed)[:_MAX_IDS]
        tables[name] = {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "ids": ids,
        }
    return {"is_first": False, "tables": tables}
