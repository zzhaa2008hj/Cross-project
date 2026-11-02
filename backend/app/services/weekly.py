"""E2 周视图服务：周键、容量、占用汇总与核对状态。

约定（来自首版计划）：
- 周键是周一日期，覆盖周一至周日；时区按 Asia/Shanghai。
- 容量来源只有两个：指定周覆盖（override）与默认周容量（default）。
  指定周显式未知（记录存在但值为空）不回退默认容量。
- 只有 Allocation 计入占用；职责（Assignment）与节点执行人不计占用。
- 未知不等于 0：容量未知时不给出精确剩余；投入未核对时同样不给出精确剩余。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Allocation,
    Assignment,
    Milestone,
    Person,
    Project,
    WeekCapacity,
    WeekReview,
)
from ..schemas import AllocationOut, AssignmentOut, MilestoneBrief, PersonWeekOut

SHANGHAI = ZoneInfo("Asia/Shanghai")
DAY_STEP = 0.5


def current_week(today: date | None = None) -> date:
    """默认周：Asia/Shanghai 当天所在周的周一。"""
    now = datetime.now(SHANGHAI)
    day = today or now.date()
    return day - timedelta(days=day.weekday())


def week_end(week: date) -> date:
    return week + timedelta(days=6)


def capacity_for(db: Session, person: Person, week: date) -> tuple[float | None, str]:
    """返回 (容量, 来源)。指定周覆盖优先；显式未知不回退默认。"""
    override = db.execute(
        select(WeekCapacity).where(
            WeekCapacity.person_id == person.id, WeekCapacity.week == week
        )
    ).scalar_one_or_none()
    if override is not None:
        return override.days, "override"
    return person.weekly_capacity, "default"


def allocation_out(db: Session, alloc: Allocation) -> AllocationOut:
    payload = AllocationOut.model_validate(alloc, from_attributes=True)
    payload.week_end = week_end(alloc.week)
    person = db.get(Person, alloc.person_id)
    project = db.get(Project, alloc.project_id)
    milestone = db.get(Milestone, alloc.milestone_id) if alloc.milestone_id else None
    payload.person_name = person.name if person else None
    payload.project_name = project.name if project else None
    payload.milestone_name = milestone.name if milestone else None
    return payload


def assignment_out(db: Session, item: Assignment) -> AssignmentOut:
    payload = AssignmentOut.model_validate(item, from_attributes=True)
    person = db.get(Person, item.person_id)
    project = db.get(Project, item.project_id)
    payload.person_name = person.name if person else None
    payload.project_name = project.name if project else None
    return payload


def list_allocations(
    db: Session,
    person_id: int | None = None,
    project_id: int | None = None,
    week: date | None = None,
) -> list[Allocation]:
    stmt = select(Allocation).order_by(Allocation.id)
    if person_id is not None:
        stmt = stmt.where(Allocation.person_id == person_id)
    if project_id is not None:
        stmt = stmt.where(Allocation.project_id == project_id)
    if week is not None:
        stmt = stmt.where(Allocation.week == week)
    return list(db.execute(stmt).scalars().all())


def reset_review(db: Session, person_id: int, week: date) -> None:
    """分配变动后，本周投入回到"待核对"。"""
    row = db.execute(
        select(WeekReview).where(WeekReview.person_id == person_id, WeekReview.week == week)
    ).scalar_one_or_none()
    if row is None:
        db.add(WeekReview(person_id=person_id, week=week, reviewed=False))
    else:
        row.reviewed = False


def is_reviewed(db: Session, person_id: int, week: date) -> bool:
    row = db.execute(
        select(WeekReview).where(WeekReview.person_id == person_id, WeekReview.week == week)
    ).scalar_one_or_none()
    return bool(row and row.reviewed)


def _round(value: float) -> float:
    return round(value + 0.0, 4)


def status_text(
    capacity: float | None, total_days: float, over_days: float | None, reviewed: bool
) -> str:
    if over_days is not None:
        return f"已填投入已超额 {_round(over_days)} 人天"
    if capacity is None:
        return "容量待确认"
    if not reviewed:
        return "投入待补充"
    return f"剩余 {_round(capacity - total_days)} 人天"


def person_week(db: Session, person: Person, week: date) -> PersonWeekOut:
    """人员某一周的全量视图。人员页与项目页共用，避免重复计入。"""
    capacity, source = capacity_for(db, person, week)
    allocations = list(
        db.execute(
            select(Allocation)
            .where(Allocation.person_id == person.id, Allocation.week == week)
            .order_by(Allocation.id)
        )
        .scalars()
        .all()
    )
    total_days = _round(sum(a.days for a in allocations))
    reviewed = is_reviewed(db, person.id, week)

    over_days: float | None = None
    if capacity is not None and total_days > capacity:
        over_days = _round(total_days - capacity)
    remaining_days: float | None = None
    if capacity is not None and reviewed:
        remaining_days = _round(capacity - total_days)

    assignments = list(
        db.execute(
            select(Assignment).where(Assignment.person_id == person.id).order_by(Assignment.id)
        )
        .scalars()
        .all()
    )

    allocated_milestone_ids = {a.milestone_id for a in allocations if a.milestone_id}
    milestones = list(
        db.execute(
            select(Milestone)
            .where(Milestone.assignee_id == person.id, Milestone.archived.is_(False))
            .order_by(Milestone.id)
        )
        .scalars()
        .all()
    )
    unallocated = [
        MilestoneBrief.model_validate(m, from_attributes=True)
        for m in milestones
        if m.id not in allocated_milestone_ids
    ]

    return PersonWeekOut(
        person_id=person.id,
        week=week,
        week_end=week_end(week),
        capacity=capacity,
        capacity_source=source,
        total_days=total_days,
        over_days=over_days,
        remaining_days=remaining_days,
        reviewed=reviewed,
        allocations=[allocation_out(db, a) for a in allocations],
        assignments=[assignment_out(db, a) for a in assignments],
        unallocated_milestones=unallocated,
        status_text=status_text(capacity, total_days, over_days, reviewed),
    )
