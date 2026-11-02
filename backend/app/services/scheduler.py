"""E4：每日一致性备份调度。

服务启动后起一个后台线程，按固定间隔做一次一致性备份。备份失败只记录日志，
不影响服务运行；``CP_BACKUP_ENABLED=0`` 可以整体关掉。
"""
from __future__ import annotations

import logging
import os
import threading

from ..config import db_path
from .backup import backup_root, default_stamp, run_backup_auto

__all__ = [
    "backup_enabled",
    "backup_interval_seconds",
    "run_scheduled_backup",
    "start_backup_scheduler",
    "stop_backup_scheduler",
]

logger = logging.getLogger(__name__)

_state = threading.Event()


def backup_enabled() -> bool:
    """每日备份开关，默认开启。"""
    return os.environ.get("CP_BACKUP_ENABLED", "1").strip() not in {"0", "false", "off"}


def backup_interval_seconds() -> int:
    """备份间隔，默认 24 小时。"""
    raw = os.environ.get("CP_BACKUP_INTERVAL_HOURS", "24").strip()
    try:
        hours = float(raw)
    except ValueError:
        hours = 24.0
    if hours <= 0:
        hours = 24.0
    return int(hours * 3600)


def run_scheduled_backup() -> dict | None:
    """做一次备份；失败只记日志并返回 ``None``。"""
    try:
        root = backup_root()
        summary = run_backup_auto(db_path(), root, default_stamp())
    except Exception as exc:  # noqa: BLE001  调度失败不能影响服务
        logger.warning("每日备份失败：%s", exc)
        return None
    logger.info("每日备份完成：%s", summary.get("stamp"))
    return summary


def _loop(interval: int) -> None:
    while not _state.wait(interval):
        run_scheduled_backup()


def start_backup_scheduler() -> threading.Thread | None:
    """启动备份调度线程；开关关闭时返回 ``None``。"""
    if not backup_enabled():
        logger.info("每日备份调度已关闭（CP_BACKUP_ENABLED）")
        return None
    _state.clear()
    thread = threading.Thread(
        target=_loop, args=(backup_interval_seconds(),), name="daily-backup", daemon=True
    )
    thread.start()
    logger.info("每日备份调度已启动，间隔 %s 秒", backup_interval_seconds())
    return thread


def stop_backup_scheduler() -> None:
    """通知调度线程退出。"""
    _state.set()
