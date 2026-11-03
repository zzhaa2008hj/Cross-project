"""应用入口。"""
from __future__ import annotations

import logging
from contextlib import ExitStack

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .api_backup import router as backup_router
from .config import db_path
from .db import init_db
from .services.restore import app_lock
from .services.scheduler import start_backup_scheduler, stop_backup_scheduler

logger = logging.getLogger(__name__)

app = FastAPI(
    title="跨项目管理软件 E2",
    description="项目/节点、依赖改期预览、人员周容量与跨项目分配",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 运行期持有的库锁：持锁期间离线恢复会被拒绝
_lock_stack = ExitStack()


@app.on_event("startup")
def _startup() -> None:
    # 先取库锁再初始化：避免第二个实例在初始化阶段动库。
    try:
        _lock_stack.enter_context(app_lock(db_path()))
    except OSError as exc:
        raise RuntimeError(f"无法取得数据库锁，可能已有实例在运行：{exc}") from exc
    init_db()
    start_backup_scheduler()


@app.on_event("shutdown")
def _shutdown() -> None:
    stop_backup_scheduler()
    _lock_stack.close()


app.include_router(router)
app.include_router(backup_router)
