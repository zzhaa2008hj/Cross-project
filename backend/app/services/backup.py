"""E4：每日一致性备份与原子发布。

备份先写 staging 目录，全部成功后再整体 rename 发布；任何一步失败都删掉 staging，
不留下半份已发布备份。备份根目录在本项目登记的 Git 外存储，绝不落在 vault 内。
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..config import data_dir
from .export import build_export, render_markdown, render_obsidian_summary
from .snapshot import snapshot_db

__all__ = ["backup_root", "run_backup", "safe_join", "default_stamp"]

DB_NAME = "crossproject.db"
JSON_NAME = "export.json"
MARKDOWN_NAME = "export.md"
OBSIDIAN_NAME = "obsidian.md"


def backup_root() -> Path:
    """备份根目录：优先 ``CP_BACKUP_DIR``，否则落在数据目录下的 ``backups/``。"""
    env = os.environ.get("CP_BACKUP_DIR")
    if env:
        return Path(env)
    return data_dir() / "backups"


def default_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def safe_join(base: Path, *parts: str) -> Path:
    """把 ``parts`` 拼到 ``base`` 下，并确保结果没有逃出 ``base``。"""
    base = Path(base)
    target = base.joinpath(*parts)
    resolved_base = base.resolve()
    resolved_target = Path(os.path.normpath(target)).resolve()
    if resolved_target != resolved_base and resolved_base not in resolved_target.parents:
        raise ValueError(f"路径逃出备份根目录：{target}")
    return target


def run_backup(db_path: Path, backup_root: Path, stamp: str | None = None) -> dict:
    """做一次一致性备份并原子发布，返回备份摘要。"""
    stamp = stamp or default_stamp()
    db_path = Path(db_path)
    root = Path(backup_root)
    root.mkdir(parents=True, exist_ok=True)

    published = safe_join(root, stamp)
    if published.exists():
        raise FileExistsError(f"备份版本已存在，拒绝覆盖：{published}")

    staging = safe_join(root, f".staging-{stamp}")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    try:
        snapshot = snapshot_db(db_path, staging / DB_NAME)
        export = build_export(snapshot)
        (staging / JSON_NAME).write_text(
            json.dumps(export, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        (staging / MARKDOWN_NAME).write_text(
            render_markdown(export), encoding="utf-8"
        )
        (staging / OBSIDIAN_NAME).write_text(
            render_obsidian_summary(export), encoding="utf-8"
        )
        os.replace(staging, published)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return {
        "stamp": stamp,
        "db_path": str(published / DB_NAME),
        "json_path": str(published / JSON_NAME),
        "markdown_path": str(published / MARKDOWN_NAME),
        "obsidian_path": str(published / OBSIDIAN_NAME),
        "counts": export["counts"],
        "snapshot_id": export["snapshot_id"],
    }
