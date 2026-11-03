from __future__ import annotations

import math
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import ASSIGNMENT_ROLES, MILESTONE_STATES, PROJECT_STATES

# 人天：非负、有限、0.5 粒度；未知用 None，与 0 严格区分
_DAY_STEP = 0.5
_NON_FINITE_STRINGS = {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity"}


def validate_days(value):
    """把人天输入归一为合法浮点数；非法值抛 ValueError（接口返回 422）。"""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("人天必须是数字，不能是布尔值")
    if isinstance(value, str) and value.strip().lower() in _NON_FINITE_STRINGS:
        raise ValueError("人天必须是有限数字")
    try:
        days = float(value)
    except (TypeError, ValueError):
        raise ValueError("人天必须是数字") from None
    if not math.isfinite(days):
        raise ValueError("人天必须是有限数字")
    if days < 0:
        raise ValueError("人天不能为负数")
    # days * 2 对极大值会溢出成 inf，round(inf) 抛 OverflowError（→ 500），
    # 这里先判有限性，把荒谬输入挡在 422 上。
    scaled = days * 2
    if not math.isfinite(scaled):
        raise ValueError("人天数值过大")
    if abs(scaled - round(scaled)) > 1e-9:
        raise ValueError("人天粒度为 0.5")
    return days


def validate_week(value: date) -> date:
    """周键必须是周一（覆盖周一至周日）。"""
    if value.weekday() != 0:
        raise ValueError("周键必须是周一日期")
    return value


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Person ----------


class PersonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    roles: str = ""
    skills: str = ""
    note: str = ""
    weekly_capacity: float | None = None
    monthly_capacity: float = 30.0

    @field_validator("weekly_capacity", mode="before")
    @classmethod
    def _check_days(cls, v):
        return validate_days(v)

    @field_validator("monthly_capacity", mode="before")
    @classmethod
    def _check_monthly(cls, v):
        if v is None:
            raise ValueError("核定人天不能为空，请填数字（默认 30）")
        return validate_days(v)


class PersonUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    roles: str | None = None
    skills: str | None = None
    note: str | None = None
    weekly_capacity: float | None = None
    monthly_capacity: float | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, v):
        if v is None:
            raise ValueError("人员姓名不能为空")
        return v

    @field_validator("weekly_capacity", mode="before")
    @classmethod
    def _check_days(cls, v):
        return validate_days(v)

    @field_validator("monthly_capacity", mode="before")
    @classmethod
    def _check_monthly(cls, v):
        if v is None:
            raise ValueError("核定人天不能为空，请填数字（默认 30）")
        return validate_days(v)


class PersonOut(ORMModel):
    id: int
    name: str
    roles: str
    skills: str
    weekly_capacity: float | None
    monthly_capacity: float
    note: str
    archived: bool
    source_ref: str | None
    edited_in_app: bool
    created_at: datetime
    updated_at: datetime


# ---------- Project ----------


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    state: str = "active"
    priority: str = ""
    progress: str = ""
    note: str = ""

    @field_validator("state")
    @classmethod
    def _check_state(cls, v: str) -> str:
        if v not in PROJECT_STATES:
            raise ValueError(f"项目状态必须是 {PROJECT_STATES} 之一")
        return v


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    state: str | None = None
    priority: str | None = None
    progress: str | None = None
    note: str | None = None
    current_focus_milestone_id: int | None = None

    @field_validator("state")
    @classmethod
    def _check_state(cls, v: str | None) -> str | None:
        if v is not None and v not in PROJECT_STATES:
            raise ValueError(f"项目状态必须是 {PROJECT_STATES} 之一")
        return v


class ProjectOut(ORMModel):
    id: int
    name: str
    state: str
    priority: str
    current_focus_milestone_id: int | None
    progress: str
    note: str
    archived: bool
    source_ref: str | None
    edited_in_app: bool
    created_at: datetime
    updated_at: datetime


class MilestoneBrief(ORMModel):
    id: int
    name: str
    state: str
    commit_date: date | None
    start_date: date | None
    assignee_id: int | None


class ProjectDetail(ProjectOut):
    milestones: list["MilestoneOut"] = []
    milestone_count: int = 0
    current_focus_name: str | None = None


# ---------- Milestone ----------


class MilestoneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    deliverable: str = ""
    start_date: date | None = None
    commit_date: date | None = None
    state: str = "未开始"
    assignee_id: int | None = None
    owner_role: str = ""
    weekly_investment_pct: float | None = None
    buffer_source: str | None = None
    workday_override: int | None = None
    progress: str = ""
    blocker_reason: str = ""
    contact_person: str = ""
    next_followup_date: date | None = None
    note: str = ""
    predecessor_ids: list[int] = []

    @field_validator("state")
    @classmethod
    def _check_state(cls, v: str) -> str:
        if v not in MILESTONE_STATES:
            raise ValueError(f"节点状态必须是 {MILESTONE_STATES} 之一")
        return v


class MilestoneUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    deliverable: str | None = None
    start_date: date | None = None
    commit_date: date | None = None
    state: str | None = None
    assignee_id: int | None = None
    owner_role: str | None = None
    weekly_investment_pct: float | None = None
    buffer_source: str | None = None
    workday_override: int | None = None
    progress: str | None = None
    blocker_reason: str | None = None
    contact_person: str | None = None
    next_followup_date: date | None = None
    note: str | None = None
    predecessor_ids: list[int] | None = None

    @field_validator("state")
    @classmethod
    def _check_state(cls, v: str | None) -> str | None:
        if v is not None and v not in MILESTONE_STATES:
            raise ValueError(f"节点状态必须是 {MILESTONE_STATES} 之一")
        return v


class MilestoneOut(ORMModel):
    id: int
    project_id: int
    name: str
    deliverable: str
    start_date: date | None
    commit_date: date | None
    state: str
    assignee_id: int | None
    owner_role: str
    weekly_investment_pct: float | None
    buffer_source: str | None
    workday_override: int | None
    progress: str
    blocker_reason: str
    contact_person: str
    next_followup_date: date | None
    note: str
    source_ref: str | None
    edited_in_app: bool
    archived: bool = False
    version: int
    created_at: datetime
    updated_at: datetime
    assignee_name: str | None = None
    predecessor_ids: list[int] = []
    buffer: dict = {}


class HistoryOut(ORMModel):
    id: int
    entity_type: str
    entity_id: int
    entity_name: str
    action: str
    field: str
    old_value: str
    new_value: str
    reason: str
    actor: str
    created_at: datetime


# ---------- 改期 ----------


class RescheduleRequest(BaseModel):
    milestone_id: int
    new_commit_date: date | None = None
    new_start_date: date | None = None
    mode: str = "current"  # current | cascade

    @field_validator("mode")
    @classmethod
    def _check_mode(cls, v: str) -> str:
        if v not in ("current", "cascade"):
            raise ValueError("mode 必须是 current 或 cascade")
        return v


class RescheduleApply(BaseModel):
    preview_id: int
    reason: str = ""  # 空白原因由服务层统一返回 400「改期原因必填」
    mode: str = "current"

    @field_validator("mode")
    @classmethod
    def _check_mode(cls, v: str) -> str:
        if v not in ("current", "cascade"):
            raise ValueError("mode 必须是 current 或 cascade")
        return v


# ---------- E2：职责 / 容量 / 分配 / 核对 ----------


class AssignmentCreate(BaseModel):
    person_id: int
    project_id: int
    role: str
    note: str = ""

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        if v not in ASSIGNMENT_ROLES:
            raise ValueError(f"职责必须是 {'/'.join(ASSIGNMENT_ROLES)} 之一")
        return v


class AssignmentUpdate(BaseModel):
    role: str | None = None
    note: str | None = None

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str | None) -> str | None:
        if v is not None and v not in ASSIGNMENT_ROLES:
            raise ValueError(f"职责必须是 {'/'.join(ASSIGNMENT_ROLES)} 之一")
        return v


class AssignmentOut(ORMModel):
    id: int
    person_id: int
    project_id: int
    role: str
    note: str
    person_name: str | None = None
    project_name: str | None = None
    created_at: datetime
    updated_at: datetime


class AllocationCreate(BaseModel):
    person_id: int
    project_id: int
    week: date
    days: float
    milestone_id: int | None = None
    kind: str = ""
    note: str = ""

    @field_validator("days", mode="before")
    @classmethod
    def _check_days(cls, v):
        return validate_days(v)

    @field_validator("week")
    @classmethod
    def _check_week(cls, v: date) -> date:
        return validate_week(v)

    @field_validator("kind")
    @classmethod
    def _check_kind(cls, v: str) -> str:
        if v and v not in ("milestone", "project_management"):
            raise ValueError("分配类型必须是 milestone 或 project_management")
        return v


class AllocationUpdate(BaseModel):
    person_id: int | None = None
    project_id: int | None = None
    week: date | None = None
    days: float | None = None
    milestone_id: int | None = None
    kind: str | None = None
    note: str | None = None

    @field_validator("days", mode="before")
    @classmethod
    def _check_days(cls, v):
        return validate_days(v)

    @field_validator("week")
    @classmethod
    def _check_week(cls, v: date | None) -> date | None:
        return validate_week(v) if v is not None else v

    @field_validator("kind")
    @classmethod
    def _check_kind(cls, v: str | None) -> str | None:
        if v and v not in ("milestone", "project_management"):
            raise ValueError("分配类型必须是 milestone 或 project_management")
        return v


class AllocationOut(ORMModel):
    id: int
    person_id: int
    project_id: int
    week: date
    week_end: date | None = None
    days: float
    milestone_id: int | None
    kind: str
    note: str
    person_name: str | None = None
    project_name: str | None = None
    milestone_name: str | None = None
    created_at: datetime
    updated_at: datetime


class WeekCapacityUpdate(BaseModel):
    days: float | None = None
    note: str = ""

    @field_validator("days", mode="before")
    @classmethod
    def _check_days(cls, v):
        return validate_days(v)


class WeekReviewUpdate(BaseModel):
    reviewed: bool


class PersonWeekOut(BaseModel):
    """人员某一周的全量视图：占用、容量、核对状态一次给全，供人员页与项目页共用。"""

    person_id: int
    week: date
    week_end: date
    capacity: float | None
    capacity_source: str  # default | override
    total_days: float
    over_days: float | None
    remaining_days: float | None
    reviewed: bool
    allocations: list[AllocationOut] = []
    assignments: list[AssignmentOut] = []
    unallocated_milestones: list[MilestoneBrief] = []
    status_text: str = ""


# ---------- 月度口径（人员页） ----------


class MonthProjectUse(BaseModel):
    """某人某月参与的项目：投入人天与职责角色分开记，职责不产生占用。"""

    project_id: int
    project_name: str
    roles: list[str] = []
    days: float = 0.0
    has_allocation: bool = False
    has_assignment: bool = False


class MonthWeekOut(BaseModel):
    """月度视图里的一周：周键是周一，week_end 是周日；周键一律用 ISO 字符串。"""

    week: str
    week_end: str
    total_days: float
    reviewed: bool
    allocations: list[AllocationOut] = []


class MonthPersonDetail(BaseModel):
    """某人某个自然月的全量视图（只读）。"""

    person_id: int
    month: str
    monthly_capacity: float
    used_days: float
    over_days: float | None
    remaining_days: float | None
    reviewed: bool
    weeks: list[MonthWeekOut] = []
    assignments: list[AssignmentOut] = []
    projects: list[MonthProjectUse] = []


# ------------------------------------------------------------------ E3 工作台


class WorkbenchTodoItem(BaseModel):
    """工作台待处理事项。kind: overdue/due_soon/blocked/unassigned/missing_allocation/capacity/review。"""

    kind: str
    project_id: int | None = None
    project_name: str | None = None
    project_state: str | None = None
    milestone_id: int | None = None
    milestone_name: str | None = None
    person_id: int | None = None
    person_name: str | None = None
    due_date: date | None = None
    week_label: str = ""
    detail: str = ""


class WorkbenchMilestone(BaseModel):
    """项目下的节点概要，带逾期/本周到期/阻塞标记。"""

    id: int
    name: str
    state: str
    commit_date: date | None = None
    start_date: date | None = None
    assignee_id: int | None = None
    assignee_name: str | None = None
    overdue: bool = False
    due_this_week: bool = False
    blocked: bool = False


class WorkbenchProject(BaseModel):
    """工作台项目行。maintenance 项目只在维护区出现。"""

    id: int
    name: str
    state: str
    on_hold: bool = False
    priority: str = ""
    priority_rank: int = 99
    current_focus_milestone_id: int | None = None
    current_focus_name: str | None = None
    allocation_days: float = 0.0
    overdue_count: int = 0
    blocked_count: int = 0
    due_soon_count: int = 0
    milestones: list[WorkbenchMilestone] = []


class WorkbenchConflict(BaseModel):
    """某人在某一周按项目归并的占用来源。"""

    project_id: int
    project_name: str | None = None
    project_state: str | None = None
    days: float = 0.0
    allocations: list[AllocationOut] = []


class WorkbenchPerson(BaseModel):
    """人员卡：与人员页同一份占用数据，不受工作台过滤裁剪。"""

    person_id: int
    name: str
    capacity: float | None = None
    capacity_source: str = "default"
    total_days: float = 0.0
    over_days: float | None = None
    remaining_days: float | None = None
    reviewed: bool = False
    status_text: str = ""
    assignments: list[AssignmentOut] = []
    allocations: list[AllocationOut] = []
    unallocated_milestones: list[MilestoneBrief] = []
    conflicts: list[WorkbenchConflict] = []


class WorkbenchOut(BaseModel):
    """工作台汇总视图：工作台、项目页、人员页共用同一份占用口径。"""

    week: date
    week_end: date
    today: date
    projects: list[WorkbenchProject] = []
    maintenance_projects: list[WorkbenchProject] = []
    people: list[WorkbenchPerson] = []
    todos: list[WorkbenchTodoItem] = []
    has_pending: bool = False
