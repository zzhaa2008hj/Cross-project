from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import MILESTONE_STATES, PROJECT_STATES


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Person ----------


class PersonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    roles: str = ""
    note: str = ""


class PersonUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    roles: str | None = None
    note: str | None = None


class PersonOut(ORMModel):
    id: int
    name: str
    roles: str
    weekly_capacity: float | None
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


# ---------- 导入 ----------


class ImportRequest(BaseModel):
    source_root: str | None = None
    apply: bool = False  # 默认 False：dry-run 不写库


class ImportRecordOut(BaseModel):
    kind: str
    source_ref: str
    source_hash: str
    status: str  # import | skip | fail
    reason: str
    mapping: dict
    diff: list[dict] = []


class ImportReportOut(BaseModel):
    id: int
    snapshot_hash: str
    mode: str
    read_count: int
    imported_count: int
    skipped_count: int
    failed_count: int
    applied: bool
    sources: list[dict]
    records: list[ImportRecordOut]
    pending: list[dict]
    diffs: list[dict]
    reconciliation: dict
    report_markdown: str
    created_at: datetime


ProjectDetail.model_rebuild()
MilestoneOut.model_rebuild()
