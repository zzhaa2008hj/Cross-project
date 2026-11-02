"""E3 工作台服务：跨项目汇总、跨周逾期、维护单列与完整冲突来源。

约定（来自 HUI-203 权威计划）：
- 工作台只读，汇总口径与人员页 /api/persons/{id}/weeks/{week} 同源，
  同一份 Allocation 在三页出现同一个稳定 ID，不重复计入。
- 逾期 = 到期日早于当前日期，且节点未完成/未取消；与选中周无关，切周不隐藏。
- 临近交付 = 选中周内尚未完成的到期节点，并标明周区间。
- maintenance 项目只在维护区展示，但其 Allocation 始终计入个人占用。
- on-hold 项目独立标识，且保留逾期与阻塞。
- 过滤（项目 / 项目负责人）只决定项目与人员范围，不裁剪人员的占用与合计。
- 只有既无异常、又没有待补数据时才算"当前没有待处理事项"。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..models import Allocation, Assignment, Milestone, Person, Project
from ..schemas import (
    WorkbenchConflict,
    WorkbenchMilestone,
    WorkbenchOut,
    WorkbenchPerson,
    WorkbenchProject,
    WorkbenchTodoItem,
)
from . import weekly as weekly_service

SHANGHAI = ZoneInfo("Asia/Shanghai")
BLOCKING_STATES = ("外部阻塞", "内部资源阻塞")
OWNER_ROLE = "项目负责人"
PRIORITY_RANK = {"P1": 1, "P2": 2, "P3": 3}
DEFAULT_PRIORITY_RANK = 99
TODO_ORDER = {
    "overdue": 0,
    "blocked": 1,
    "due_soon": 2,
    "unassigned": 3,
    "missing_allocation": 4,
    "capacity": 5,
    "review": 6,
}


def today_shanghai() -> date:
    """当前日期（Asia/Shanghai）。测试可替换本函数固定"今天"。"""
    return datetime.now(SHANGHAI).date()


def _round(value: float) -> float:
    return round(value + 0.0, 4)


def _week_label(week: date) -> str:
    return f"{week.isoformat()} ~ {(week + timedelta(days=6)).isoformat()}"


def _priority_rank(priority: str) -> int:
    return PRIORITY_RANK.get((priority or "").strip().upper(), DEFAULT_PRIORITY_RANK)


def _is_terminal(state: str) -> bool:
    return state in config.TERMINAL_MILESTONE_STATES


def _is_blocked(milestone: Milestone) -> bool:
    return milestone.state in BLOCKING_STATES or bool((milestone.blocker_reason or "").strip())


def build_workbench(
    db: Session,
    week: date,
    project_id: int | None = None,
    owner_person_id: int | None = None,
) -> WorkbenchOut:
    """汇总工作台。week 必须是周一日期。"""
    today = today_shanghai()
    week_end = week + timedelta(days=6)
    label = _week_label(week)

    projects = list(
        db.execute(
            select(Project).where(Project.archived.is_(False)).order_by(Project.id)
        ).scalars().all()
    )
    assignments = list(
        db.execute(select(Assignment).order_by(Assignment.id)).scalars().all()
    )
    allocations = list(
        db.execute(
            select(Allocation).where(Allocation.week == week).order_by(Allocation.id)
        ).scalars().all()
    )
    milestones = list(
        db.execute(
            select(Milestone).where(Milestone.archived.is_(False)).order_by(Milestone.id)
        ).scalars().all()
    )

    # --- 过滤：只决定项目范围 -------------------------------------------
    owner_project_ids: set[int] | None = None
    if owner_person_id is not None:
        owner_project_ids = {
            a.project_id
            for a in assignments
            if a.person_id == owner_person_id and a.role == OWNER_ROLE
        }
    scoped: list[Project] = []
    for project in projects:
        if project_id is not None and project.id != project_id:
            continue
        if owner_project_ids is not None and project.id not in owner_project_ids:
            continue
        scoped.append(project)
    scoped_ids = {p.id for p in scoped}

    # --- 人员范围：范围内项目的负责人/执行人 + 本周有占用的人 -----------
    people_rows = list(
        db.execute(
            select(Person).where(Person.archived.is_(False)).order_by(Person.id)
        ).scalars().all()
    )
    scoped_people = [
        person
        for person in people_rows
        if any(
            a.person_id == person.id and a.project_id in scoped_ids for a in assignments
        )
        or any(al.person_id == person.id for al in allocations)
    ]

    milestones_by_project: dict[int, list[Milestone]] = {}
    for milestone in milestones:
        milestones_by_project.setdefault(milestone.project_id, []).append(milestone)

    person_names = {p.id: p.name for p in people_rows}
    project_names = {p.id: p.name for p in projects}
    project_states = {p.id: p.state for p in projects}

    todos: list[WorkbenchTodoItem] = []

    # --- 项目维度：逾期 / 临近交付 / 阻塞 / 待分派 -----------------------
    project_rows: dict[int, WorkbenchProject] = {}
    for project in scoped:
        if project.state == "done":
            continue
        ms_items: list[WorkbenchMilestone] = []
        overdue_count = blocked_count = due_soon_count = 0
        for milestone in milestones_by_project.get(project.id, []):
            terminal = _is_terminal(milestone.state)
            commit = milestone.commit_date
            overdue = bool(commit and not terminal and commit < today)
            due_this_week = bool(commit and not terminal and week <= commit <= week_end)
            blocked = _is_blocked(milestone)
            ms_items.append(
                WorkbenchMilestone(
                    id=milestone.id,
                    name=milestone.name,
                    state=milestone.state,
                    commit_date=commit,
                    start_date=milestone.start_date,
                    assignee_id=milestone.assignee_id,
                    assignee_name=person_names.get(milestone.assignee_id),
                    overdue=overdue,
                    due_this_week=due_this_week,
                    blocked=blocked,
                )
            )
            if overdue:
                overdue_count += 1
                todos.append(
                    WorkbenchTodoItem(
                        kind="overdue",
                        project_id=project.id,
                        project_name=project.name,
                        project_state=project.state,
                        milestone_id=milestone.id,
                        milestone_name=milestone.name,
                        person_id=milestone.assignee_id,
                        person_name=person_names.get(milestone.assignee_id),
                        due_date=commit,
                        week_label=label,
                        detail=f"节点「{milestone.name}」已于 {commit.isoformat()} 到期，尚未完成",
                    )
                )
            if due_this_week:
                due_soon_count += 1
                todos.append(
                    WorkbenchTodoItem(
                        kind="due_soon",
                        project_id=project.id,
                        project_name=project.name,
                        project_state=project.state,
                        milestone_id=milestone.id,
                        milestone_name=milestone.name,
                        person_id=milestone.assignee_id,
                        person_name=person_names.get(milestone.assignee_id),
                        due_date=commit,
                        week_label=label,
                        detail=f"节点「{milestone.name}」在 {label} 内到期，尚未完成",
                    )
                )
            if blocked:
                blocked_count += 1
                todos.append(
                    WorkbenchTodoItem(
                        kind="blocked",
                        project_id=project.id,
                        project_name=project.name,
                        project_state=project.state,
                        milestone_id=milestone.id,
                        milestone_name=milestone.name,
                        person_id=milestone.assignee_id,
                        person_name=person_names.get(milestone.assignee_id),
                        due_date=commit,
                        week_label=label,
                        detail=f"节点「{milestone.name}」处于{ milestone.state }",
                    )
                )
            if milestone.assignee_id is None and not terminal:
                todos.append(
                    WorkbenchTodoItem(
                        kind="unassigned",
                        project_id=project.id,
                        project_name=project.name,
                        project_state=project.state,
                        milestone_id=milestone.id,
                        milestone_name=milestone.name,
                        due_date=commit,
                        week_label=label,
                        detail=f"节点「{milestone.name}」尚未指定执行人",
                    )
                )

        allocation_days = _round(
            sum(al.days for al in allocations if al.project_id == project.id)
        )
        focus_name = None
        if project.current_focus_milestone_id:
            focus = db.get(Milestone, project.current_focus_milestone_id)
            focus_name = focus.name if focus else None
        project_rows[project.id] = WorkbenchProject(
            id=project.id,
            name=project.name,
            state=project.state,
            on_hold=project.state == "on-hold",
            priority=project.priority or "",
            priority_rank=_priority_rank(project.priority or ""),
            current_focus_milestone_id=project.current_focus_milestone_id,
            current_focus_name=focus_name,
            allocation_days=allocation_days,
            overdue_count=overdue_count,
            blocked_count=blocked_count,
            due_soon_count=due_soon_count,
            milestones=ms_items,
        )

    # --- 人员维度：占用、冲突来源与待补数据 -----------------------------
    person_cards: list[WorkbenchPerson] = []
    for person in scoped_people:
        card = weekly_service.person_week(db, person, week)
        conflicts: dict[int, WorkbenchConflict] = {}
        for allocation in card.allocations:
            conflict = conflicts.get(allocation.project_id)
            if conflict is None:
                conflict = WorkbenchConflict(
                    project_id=allocation.project_id,
                    project_name=allocation.project_name,
                    project_state=project_states.get(allocation.project_id),
                    days=0.0,
                    allocations=[],
                )
                conflicts[allocation.project_id] = conflict
            conflict.days = _round(conflict.days + allocation.days)
            conflict.allocations.append(allocation)
        person_cards.append(
            WorkbenchPerson(
                person_id=person.id,
                name=person.name,
                capacity=card.capacity,
                capacity_source=card.capacity_source,
                total_days=card.total_days,
                over_days=card.over_days,
                remaining_days=card.remaining_days,
                reviewed=card.reviewed,
                status_text=card.status_text,
                assignments=card.assignments,
                allocations=card.allocations,
                unallocated_milestones=card.unallocated_milestones,
                conflicts=list(conflicts.values()),
            )
        )
        if card.capacity is None:
            todos.append(
                WorkbenchTodoItem(
                    kind="capacity",
                    person_id=person.id,
                    person_name=person.name,
                    project_id=None,
                    project_name=None,
                    week_label=label,
                    detail=f"{person.name} 的周容量待确认",
                )
            )
        if not card.reviewed:
            todos.append(
                WorkbenchTodoItem(
                    kind="review",
                    person_id=person.id,
                    person_name=person.name,
                    week_label=label,
                    detail=f"{person.name} 本周投入待补充/核对",
                )
            )
        for brief in card.unallocated_milestones:
            milestone = db.get(Milestone, brief.id)
            if milestone is None or _is_terminal(milestone.state):
                continue
            if milestone.project_id not in scoped_ids:
                continue
            todos.append(
                WorkbenchTodoItem(
                    kind="missing_allocation",
                    project_id=milestone.project_id,
                    project_name=project_names.get(milestone.project_id),
                    project_state=project_states.get(milestone.project_id),
                    milestone_id=milestone.id,
                    milestone_name=milestone.name,
                    person_id=person.id,
                    person_name=person.name,
                    due_date=milestone.commit_date,
                    week_label=label,
                    detail=f"{person.name} 的节点「{milestone.name}」本周尚未填写投入",
                )
            )

    todos.sort(
        key=lambda t: (
            TODO_ORDER.get(t.kind, 99),
            t.project_id if t.project_id is not None else 0,
            t.milestone_id if t.milestone_id is not None else 0,
            t.person_id if t.person_id is not None else 0,
        )
    )

    rows = sorted(
        project_rows.values(),
        key=lambda row: (row.priority_rank, row.name, row.id),
    )
    deliverable = [r for r in rows if r.state != "maintenance"]
    maintenance = [r for r in rows if r.state == "maintenance"]

    return WorkbenchOut(
        week=week,
        week_end=week_end,
        today=today,
        projects=deliverable,
        maintenance_projects=maintenance,
        people=person_cards,
        todos=todos,
        has_pending=bool(todos),
    )
