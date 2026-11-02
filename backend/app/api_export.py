"""E4：导出预览 API 与手动备份触发。

预览只读取软件数据库的一致性快照，产物落在数据目录的 ``exports/`` 下，
不写回 vault 笔记，也不覆盖任何既有文件。
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

from .config import db_path, exports_dir
from .services.backup import backup_root, default_stamp, run_backup_auto
from .services.export import (
    build_export,
    diff_exports,
    render_markdown,
    render_obsidian_summary,
)
from .services.snapshot import snapshot_db

__all__ = ["router"]

router = APIRouter()

_PREVIEW_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MAX_INDEX_ITEMS = 20
_JSON_NAME = "export.json"
_MARKDOWN_NAME = "export.md"
_OBSIDIAN_NAME = "obsidian.md"


def _index_path() -> Path:
    return exports_dir() / "index.json"


def _read_index() -> list[dict]:
    path = _index_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def _write_index(items: list[dict]) -> None:
    exports_dir().mkdir(parents=True, exist_ok=True)
    _index_path().write_text(
        json.dumps({"items": items[:_MAX_INDEX_ITEMS]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _preview_id(export: dict) -> str:
    """预览编号：微秒级时间戳 + 内容散列，保证每次预览都有独立目录。"""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    digest = str(export.get("snapshot_id", "")).rsplit("-", 1)[-1] or "00000000"
    return f"prev-{stamp}-{digest}"


def _build_export_payload() -> dict:
    """从一致性快照构建导出内容，不触碰现库。"""
    root = exports_dir()
    root.mkdir(parents=True, exist_ok=True)
    snapshot = root / f".snapshot-{uuid.uuid4().hex}.db"
    try:
        snapshot_db(db_path(), snapshot)
        export = build_export(snapshot)
    finally:
        for stale in (snapshot, Path(str(snapshot) + "-wal"), Path(str(snapshot) + "-shm")):
            if stale.exists():
                stale.unlink()
    return export


def _previous_export(items: list[dict]) -> dict | None:
    """上一次预览的导出内容，用于算差异。"""
    for item in items:
        path = exports_dir() / str(item.get("preview_id")) / _JSON_NAME
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return None


def create_preview() -> dict:
    """生成一次预览：JSON / Markdown / Obsidian 三份产物 + 与上次的差异。"""
    export = _build_export_payload()
    markdown = render_markdown(export)
    obsidian = render_obsidian_summary(export)

    items = _read_index()
    diff = diff_exports(_previous_export(items), export)

    preview_id = _preview_id(export)
    folder = exports_dir() / preview_id
    folder.mkdir(parents=True, exist_ok=False)
    (folder / _JSON_NAME).write_text(
        json.dumps(export, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (folder / _MARKDOWN_NAME).write_text(markdown, encoding="utf-8")
    (folder / _OBSIDIAN_NAME).write_text(obsidian, encoding="utf-8")

    item = {
        "preview_id": preview_id,
        "generated_at": export.get("generated_at", ""),
        "snapshot_id": export.get("snapshot_id", ""),
        "counts": export.get("counts", {}),
    }
    _write_index([item] + items)

    return {
        "preview_id": preview_id,
        "generated_at": item["generated_at"],
        "snapshot_id": item["snapshot_id"],
        "counts": item["counts"],
        "diff": diff,
        "markdown": markdown,
        "obsidian": obsidian,
    }


def _preview_folder(preview_id: str) -> Path:
    """定位预览目录：编号合法、不是符号链接、且确实在导出目录内。"""
    if not _PREVIEW_ID_RE.match(preview_id or ""):
        raise HTTPException(status_code=404, detail="预览不存在")
    folder = exports_dir() / preview_id
    if folder.is_symlink() or not folder.is_dir():
        raise HTTPException(status_code=404, detail="预览不存在")
    root = exports_dir().resolve()
    try:
        resolved = folder.resolve()
    except OSError:
        raise HTTPException(status_code=404, detail="预览不存在") from None
    if resolved != root and root not in resolved.parents:
        raise HTTPException(status_code=404, detail="预览不存在")
    return folder


def _read_preview_file(preview_id: str, name: str) -> str:
    path = _preview_folder(preview_id) / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="预览产物不存在")
    return path.read_text(encoding="utf-8")


@router.post("/api/export/preview")
def post_preview() -> dict:
    return create_preview()


@router.get("/api/export/previews")
def get_previews() -> dict:
    return {"items": _read_index()[:_MAX_INDEX_ITEMS]}


@router.get("/api/export/previews/{preview_id}/json")
def get_preview_json(preview_id: str) -> JSONResponse:
    return JSONResponse(content=json.loads(_read_preview_file(preview_id, _JSON_NAME)))


@router.get("/api/export/previews/{preview_id}/markdown")
def get_preview_markdown(preview_id: str) -> PlainTextResponse:
    return PlainTextResponse(
        _read_preview_file(preview_id, _MARKDOWN_NAME),
        media_type="text/markdown; charset=utf-8",
    )


@router.get("/api/export/previews/{preview_id}/obsidian")
def get_preview_obsidian(preview_id: str) -> PlainTextResponse:
    return PlainTextResponse(
        _read_preview_file(preview_id, _OBSIDIAN_NAME),
        media_type="text/markdown; charset=utf-8",
    )


@router.post("/api/backup/run")
def post_backup_run() -> dict:
    """手动触发一次一致性备份，返回备份摘要。

    版本号精确到秒，同一秒内重复触发会自动顺延序号，避免直接失败。
    """
    root = backup_root()
    try:
        return run_backup_auto(db_path(), root, default_stamp())
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
