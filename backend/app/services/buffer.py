"""缓冲派生（80/20 规则）。

口径来自首版计划：
- 窗口 W = 开始日 ~ 承诺日（含首尾）的周一至周五天数，不内置法定节假日历
- B = max(floor(W * 0.2 + 0.5), 1)
- 内部目标日 = 承诺日向前数 B 个工作日；仅作派生提示，不覆盖承诺日
- 缺日期 / 开始日晚于承诺日 / W=0 -> 待确认，不给伪精确值
- 内部目标早于开始日 -> 窗口不足
- 缓冲来源含"外部" -> 不提供消费操作（consumable=False，无内部目标日）
"""
from __future__ import annotations

import math
from datetime import date, timedelta

EXTERNAL_MARKER = "外部"


def is_workday(d: date) -> bool:
    return d.weekday() < 5


def workday_count(start: date, commit: date) -> int:
    """开始日到承诺日（含首尾）之间的周一至周五天数。"""
    if commit < start:
        return 0
    total = 0
    cursor = start
    while cursor <= commit:
        if is_workday(cursor):
            total += 1
        cursor += timedelta(days=1)
    return total


def buffer_days(window: int) -> int:
    return max(math.floor(window * 0.2 + 0.5), 1)


def subtract_workdays(d: date, count: int) -> date:
    """从 d 向前数 count 个工作日（d 本身若为工作日则计入）。"""
    if count <= 0:
        return d
    cursor = d
    remaining = count
    while remaining > 0:
        cursor -= timedelta(days=1)
        if is_workday(cursor):
            remaining -= 1
    return cursor


def is_external(buffer_source: str | None) -> bool:
    return bool(buffer_source) and EXTERNAL_MARKER in buffer_source


def derive_buffer(
    start_date: date | None,
    commit_date: date | None,
    buffer_source: str | None = None,
    workday_override: int | None = None,
) -> dict:
    """返回缓冲派生结果。

    字段：status / window_workdays / buffer_days / internal_target /
          consumable / reason / warnings
    """
    result: dict = {
        "status": "待确认",
        "window_workdays": None,
        "buffer_days": None,
        "internal_target": None,
        "consumable": False,
        "reason": "",
        "warnings": [],
        "commit_on_weekend": False,
        "start_after_commit": False,
    }

    if commit_date is None:
        result["reason"] = "缺少承诺日"
        return result
    if commit_date.weekday() >= 5:
        result["commit_on_weekend"] = True
        result["warnings"].append("承诺日落在周末，保留原值并标注")

    if start_date is None:
        result["reason"] = "缺少开始日"
        return result
    if start_date > commit_date:
        result["start_after_commit"] = True
        result["reason"] = "开始日晚于承诺日"
        return result

    window = workday_count(start_date, commit_date)
    if workday_override is not None:
        window = workday_override
    if window <= 0:
        result["reason"] = "窗口内无工作日"
        return result

    b = buffer_days(window)
    result["window_workdays"] = window
    result["buffer_days"] = b
    result["status"] = "ok"

    if is_external(buffer_source):
        result["consumable"] = False
        result["reason"] = "缓冲来源为外部，不提供消费操作"
        return result

    result["consumable"] = True
    target = subtract_workdays(commit_date, b)
    result["internal_target"] = target.isoformat()
    if target < start_date:
        result["status"] = "窗口不足"
        result["consumable"] = False
        result["reason"] = f"内部目标日 {target.isoformat()} 早于开始日 {start_date.isoformat()}"
    return result
