"""月度口径服务：自然月的周集合与单人月度视图。

约定（与周视图 weekly.py 保持一致）：
- 周键是周一日期；自然月按「周一落在该月」归集，跨月的那一周整周算进起始月。
- 占用只来自 Allocation（周投入）；职责（Assignment）不产生占用，只在项目维度上出现。
- 未知不等于 0：核定人天必有值，但本月有投入尚未核对时不给精确剩余。
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Allocation, Assignment, Person, Project
from ..schemas import MonthPersonDetail, MonthProjectUse, MonthWeekOut
from . import weekly as weekly_service


def parse_month(month: str) -> tuple[int, int]:
    """解析 YYYY-MM；非法格式返回 400，不抛 500。"""
    parts = (month or "").split("-")
    if len(parts) != 2 or not all(p.isdecimal() for p in parts):
        raise HTTPException(status_code=400, detail="月份格式应为 YYYY-MM")
    # YYYY-MM 是定宽格式：年四位、月两位，"2026-1" 不算合法月份。
    if len(parts[0]) != 4 or len(parts[1]) != 2:
        raise HTTPException(status_code=400, detail="月份格式应为 YYYY-MM")
    year, mon = int(parts[0]), int(parts[1])
    # 年份必须在 date() 能表示的范围内，否则后面构造日期会抛 ValueError（→ 500）。
    if not 1 <= year <= 9999 or not 1 <= mon <= 12:
        raise HTTPException(status_code=400, detail="月份格式应为 YYYY-MM")
    return year, mon


def month_weeks(month: str) -> list[str]:
    """该自然月内所有「周一落在该月」的日期，升序。"""
    year, mon = parse_month(month)
    last_day = calendar.monthrange(year, mon)[1]
    d = date(year, mon, 1)
    while d.weekday() != 0:          # 找到该月第一个周一
        d = d + timedelta(days=1)
    month_end = date(year, mon, last_day)
    # 收几条按「本月第一个周一到月末」的天数差一次算清，等价于逐个 +7 天后
    # 与月末做日期比较：d.day == 7 <= 30 那种比较会把下一月的周一错收进来。
    # 先算条数也避免了收完最后一周再 +7 天越过 date.max（9999-12 会溢出）。
    count = (month_end - d).days // 7 + 1
    return [(d + timedelta(days=7 * i)).isoformat() for i in range(count)]


def _project_uses(
    db: Session, allocations: list[Allocation], assignments: list[Assignment]
) -> list[MonthProjectUse]:
    """按项目合并投入与职责：投入算人天，职责只挂角色，不产生占用。"""
    days_by_project: dict[int, float] = {}
    roles_by_project: dict[int, list[str]] = {}
    for alloc in allocations:
        days_by_project[alloc.project_id] = (
            days_by_project.get(alloc.project_id, 0.0) + alloc.days
        )
    for item in assignments:
        roles_by_project.setdefault(item.project_id, []).append(item.role)

    out = []
    for pid in sorted(set(days_by_project) | set(roles_by_project)):
        project = db.get(Project, pid)
        out.append(
            MonthProjectUse(
                project_id=pid,
                project_name=project.name if project else "",
                roles=roles_by_project.get(pid, []),
                days=round(days_by_project.get(pid, 0.0), 4),
                has_allocation=pid in days_by_project,
                has_assignment=pid in roles_by_project,
            )
        )
    return out


def person_month(db: Session, person: Person, month: str) -> MonthPersonDetail:
    """某人某个自然月的全量视图（只读）。"""
    weeks = [date.fromisoformat(w) for w in month_weeks(month)]
    allocations = list(
        db.execute(
            select(Allocation)
            .where(Allocation.person_id == person.id, Allocation.week.in_(weeks))
            .order_by(Allocation.id)
        )
        .scalars()
        .all()
    )
    assignments = list(
        db.execute(
            select(Assignment).where(Assignment.person_id == person.id).order_by(Assignment.id)
        )
        .scalars()
        .all()
    )

    capacity = person.monthly_capacity
    used_days = round(sum(a.days for a in allocations), 4)
    over_days = round(used_days - capacity, 4) if used_days > capacity else None

    # 只有「有投入的周」参与核对判定：空周没有投入可核对，不阻塞。
    alloc_weeks = {a.week for a in allocations}
    reviewed = all(weekly_service.is_reviewed(db, person.id, w) for w in alloc_weeks)
    remaining_days = round(capacity - used_days, 4) if reviewed else None

    by_week: dict[date, list[Allocation]] = {}
    for alloc in allocations:
        by_week.setdefault(alloc.week, []).append(alloc)
    week_rows = []
    for w in weeks:
        rows = by_week.get(w, [])
        week_rows.append(
            MonthWeekOut(
                week=w.isoformat(),
                week_end=weekly_service.week_end(w).isoformat(),
                total_days=round(sum(a.days for a in rows), 4),
                reviewed=weekly_service.is_reviewed(db, person.id, w),
                allocations=[weekly_service.allocation_out(db, a) for a in rows],
            )
        )

    return MonthPersonDetail(
        person_id=person.id,
        month=month,
        monthly_capacity=capacity,
        used_days=used_days,
        over_days=over_days,
        remaining_days=remaining_days,
        reviewed=reviewed,
        weeks=week_rows,
        assignments=[weekly_service.assignment_out(db, a) for a in assignments],
        projects=_project_uses(db, allocations, assignments),
    )
