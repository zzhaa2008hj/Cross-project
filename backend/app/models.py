"""数据模型。

边界说明：占用只来自 Allocation（周投入）表；分派节点执行人只写 assignee_id，
项目职责（Assignment）也不产生占用记录。E2 起启用周容量与 0.5 人天分配。
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Person(Base):
    __tablename__ = "persons"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    roles: Mapped[str] = mapped_column(String(255), default="")
    skills: Mapped[str] = mapped_column(String(255), default="")
    # 默认周容量：留空代表未知（与 0 严格区分）；E2 起可被指定周覆盖
    weekly_capacity: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_record_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    edited_in_app: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    state: Mapped[str] = mapped_column(String(32), default="active")
    priority: Mapped[str] = mapped_column(String(32), default="")
    # 手动当前重点：只存 milestone id，不自动取最近到期节点
    current_focus_milestone_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_record_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    edited_in_app: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    milestones: Mapped[list["Milestone"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    deliverable: Mapped[str] = mapped_column(Text, default="")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    commit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    state: Mapped[str] = mapped_column(String(32), default="未开始")
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("persons.id"), nullable=True)
    owner_role: Mapped[str] = mapped_column(String(120), default="")
    weekly_investment_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    buffer_source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    workday_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress: Mapped[str] = mapped_column(Text, default="")
    blocker_reason: Mapped[str] = mapped_column(Text, default="")
    contact_person: Mapped[str] = mapped_column(Text, default="")
    next_followup_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_record_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_dep_names: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_in_app: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    project: Mapped[Project] = relationship(back_populates="milestones")
    assignee: Mapped[Person | None] = relationship()
    dependencies: Mapped[list["MilestoneDependency"]] = relationship(
        back_populates="milestone",
        foreign_keys="MilestoneDependency.milestone_id",
        cascade="all, delete-orphan",
    )


class MilestoneDependency(Base):
    """前置 -> 节点。首版只支持同项目依赖。"""

    __tablename__ = "milestone_dependencies"
    __table_args__ = (UniqueConstraint("milestone_id", "predecessor_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    milestone_id: Mapped[int] = mapped_column(ForeignKey("milestones.id"), index=True)
    predecessor_id: Mapped[int] = mapped_column(ForeignKey("milestones.id"), index=True)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    milestone: Mapped[Milestone] = relationship(
        back_populates="dependencies", foreign_keys=[milestone_id]
    )


class HistoryEntry(Base):
    __tablename__ = "history_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[int] = mapped_column(Integer)
    entity_name: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(32))
    field: Mapped[str] = mapped_column(String(64), default="")
    old_value: Mapped[str] = mapped_column(Text, default="")
    new_value: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ImportRun(Base):
    __tablename__ = "import_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(16))  # dry_run | apply
    read_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    report_json: Mapped[str] = mapped_column(Text, default="")
    report_markdown: Mapped[str] = mapped_column(Text, default="")
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Assignment(Base):
    """项目职责：只记录"谁在项目里担什么角色"，不产生任何占用。"""

    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("person_id", "project_id", "role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    role: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class WeekCapacity(Base):
    """指定周容量覆盖。days 为 NULL 表示"显式未知"，不回退默认容量。"""

    __tablename__ = "week_capacities"
    __table_args__ = (UniqueConstraint("person_id", "week"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    week: Mapped[date] = mapped_column(Date, index=True)
    days: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Allocation(Base):
    """周投入分配：唯一占用来源。关联节点，或表示"整体项目管理"投入。"""

    __tablename__ = "allocations"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    week: Mapped[date] = mapped_column(Date, index=True)
    days: Mapped[float] = mapped_column(Float)
    milestone_id: Mapped[int | None] = mapped_column(ForeignKey("milestones.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default="milestone")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class WeekReview(Base):
    """本周投入是否已人工核对。分配一旦变动即失效。"""

    __tablename__ = "week_reviews"
    __table_args__ = (UniqueConstraint("person_id", "week"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    week: Mapped[date] = mapped_column(Date, index=True)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class ReschedulePreview(Base):
    __tablename__ = "reschedule_previews"

    id: Mapped[int] = mapped_column(primary_key=True)
    milestone_id: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(16))
    payload_json: Mapped[str] = mapped_column(Text, default="")
    versions_json: Mapped[str] = mapped_column(Text, default="")
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
