"""E4：备份接口。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .config import db_path
from .services.backup import backup_root, default_stamp, run_backup_auto

router = APIRouter()


@router.post("/api/backup/run")
def post_backup_run() -> dict:
    root = backup_root()
    try:
        return run_backup_auto(db_path(), root, default_stamp())
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
