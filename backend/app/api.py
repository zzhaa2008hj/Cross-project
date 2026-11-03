"""HTTP 接口层。"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config
from .db import get_db
from .models import (
    Allocation,
    Assignment,
    HistoryEntry,
    Milestone,
    MilestoneDependency,
    Person,
    Project,
    WeekCapacity,
    WeekReview,
)
from .schemas import (
    AllocationCreate,
    AllocationOut,
    AllocationUpdate,
    AssignmentCreate,
    AssignmentOut,
    AssignmentUpdate,
    HistoryOut,
    MilestoneCreate,
    MilestoneOut,
    MilestoneUpdate,
    PersonCreate,
    PersonOut,
    PersonUpdate,
    PersonWeekOut,
    ProjectCreate,
    ProjectDetail,
    ProjectOut,
    ProjectUpdate,
    RescheduleApply,
    RescheduleRequest,
    WeekCapacityUpdate,
    WeekReviewUpdate,
    WorkbenchOut,
)
from .services import buffer as buffer_service
from .services import history as history_service
from .services import reschedule as reschedule_service
from .services import weekly as weekly_service
from .services import workbench as workbench_service

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ 序列化


def milestone_out(db: Session, ms: Milestone) -> MilestoneOut:
    payload = MilestoneOut.model_validate(ms, from_attributes=True)
    payload.assignee_name = ms.assignee.name if ms.assignee else None
    payload.predecessor_ids = sorted(d.predecessor_id for d in ms.dependencies)
    payload.buffer = buffer_service.derive_buffer(
        ms.start_date, ms.commit_date, ms.buffer_source, ms.workday_override
    )
    return payload


def project_detail(db: Session, project: Project) -> ProjectDetail:
    payload = ProjectDetail.model_validate(project, from_attributes=True)
    payload.milestones = [milestone_out(db, m) for m in project.milestones]
    payload.milestone_count = len(project.milestones)
    payload.current_focus_name = None
    if project.current_focus_milestone_id:
        focus = db.get(Milestone, project.current_focus_milestone_id)
        payload.current_focus_name = focus.name if focus else None
    return payload


# ------------------------------------------------------------------ 元信息


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    count = db.execute(select(func.count()).select_from(Project)).scalar_one()
    return {"status": "ok", "projects": count, "company_id": config.COMPANY_ID}


@router.get("/meta")
def meta() -> dict:
    return {
        "project_states": list(config.PROJECT_STATES),
        "milestone_states": list(config.MILESTONE_STATES),
        "terminal_milestone_states": list(config.TERMINAL_MILESTONE_STATES),
        "allocation_supported": True,
    }


# ------------------------------------------------------------------ 人员


@router.get("/persons", response_model=list[PersonOut])
def list_persons(include_archived: bool = False, db: Session = Depends(get_db)):
    stmt = select(Person).order_by(Person.name)
    if not include_archived:
        stmt = stmt.where(Person.archived.is_(False))
    return db.execute(stmt).scalars().all()


@router.post("/persons", response_model=PersonOut, status_code=201)
def create_person(payload: PersonCreate, db: Session = Depends(get_db)):
    exists = db.execute(select(Person).where(Person.name == payload.name)).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail=f"人员「{payload.name}」已存在")
    person = Person(
        name=payload.name,
        roles=payload.roles,
        skills=payload.skills,
        note=payload.note,
        weekly_capacity=payload.weekly_capacity,
        monthly_capacity=payload.monthly_capacity,
        edited_in_app=True,
    )
    db.add(person)
    db.flush()
    history_service.record(db, "person", person.id, person.name, "create")
    db.commit()
    db.refresh(person)
    return person


@router.patch("/persons/{person_id}", response_model=PersonOut)
def update_person(person_id: int, payload: PersonUpdate, db: Session = Depends(get_db)):
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="人员不存在")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        dup = db.execute(
            select(Person).where(Person.name == data["name"], Person.id != person_id)
        ).scalar_one_or_none()
        if dup:
            raise HTTPException(status_code=409, detail=f"人员「{data['name']}」已存在")
    for field in ("roles", "skills", "note"):
        if field in data and data[field] is None:
            data[field] = ""
    for field, value in data.items():
        setattr(person, field, value)
    person.edited_in_app = True
    history_service.record(db, "person", person.id, person.name, "update", reason="人员资料更新")
    db.commit()
    db.refresh(person)
    return person


@router.post("/persons/{person_id}/archive", response_model=PersonOut)
def archive_person(person_id: int, db: Session = Depends(get_db)):
    """归档人员：保留历史与既有分配，不做物理删除。"""
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="人员不存在")
    if not person.archived:
        person.archived = True
        person.edited_in_app = True
        history_service.record(
            db, "person", person.id, person.name, "archive", "archived", False, True, "人员归档"
        )
        db.commit()
        db.refresh(person)
    return person


@router.post("/persons/{person_id}/restore", response_model=PersonOut)
def restore_person(person_id: int, db: Session = Depends(get_db)):
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="人员不存在")
    person.archived = False
    person.edited_in_app = True
    history_service.record(
        db, "person", person.id, person.name, "restore", "archived", True, False, "人员恢复"
    )
    db.commit()
    db.refresh(person)
    return person


# ------------------------------------------------------------------ 项目


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(
    state: str | None = None,
    include_archived: bool = False,
    db: Session = Depends(get_db),
):
    stmt = select(Project).order_by(Project.name)
    if not include_archived:
        stmt = stmt.where(Project.archived.is_(False))
    if state:
        if state not in config.PROJECT_STATES:
            raise HTTPException(status_code=400, detail=f"未知项目状态「{state}」")
        stmt = stmt.where(Project.state == state)
    return db.execute(stmt).scalars().all()


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    exists = db.execute(select(Project).where(Project.name == payload.name)).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail=f"项目「{payload.name}」已存在")
    project = Project(**payload.model_dump(), edited_in_app=True)
    db.add(project)
    db.flush()
    history_service.record(db, "project", project.id, project.name, "create")
    db.commit()
    db.refresh(project)
    return project


@router.get("/projects/{project_id}", response_model=ProjectDetail)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project_detail(db, project)


@router.patch("/projects/{project_id}", response_model=ProjectDetail)
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    data = payload.model_dump(exclude_unset=True)
    focus = data.pop("current_focus_milestone_id", None)
    for field, value in data.items():
        old = getattr(project, field)
        if old != value:
            setattr(project, field, value)
            history_service.record(
                db, "project", project.id, project.name, "update", field, old, value, "项目信息更新"
            )
    if focus is not None:
        if focus != project.current_focus_milestone_id:
            old_focus = project.current_focus_milestone_id
            target = db.get(Milestone, focus)
            if target is None or target.project_id != project.id:
                raise HTTPException(status_code=400, detail="当前重点必须指向本项目下的节点")
            project.current_focus_milestone_id = focus
            history_service.record(
                db,
                "project",
                project.id,
                project.name,
                "update",
                "current_focus_milestone_id",
                old_focus,
                focus,
                "手动设置当前重点",
            )
    project.edited_in_app = True
    db.commit()
    db.refresh(project)
    return project_detail(db, project)


@router.post("/projects/{project_id}/archive", response_model=ProjectDetail)
def archive_project(project_id: int, db: Session = Depends(get_db)):
    """归档项目：保留全部节点与历史，不做级联删除。"""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not project.archived:
        project.archived = True
        project.edited_in_app = True
        history_service.record(
            db, "project", project.id, project.name, "archive", "archived", False, True, "项目归档"
        )
        db.commit()
        db.refresh(project)
    return project_detail(db, project)


@router.post("/projects/{project_id}/restore", response_model=ProjectDetail)
def restore_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    project.archived = False
    project.edited_in_app = True
    history_service.record(
        db, "project", project.id, project.name, "restore", "archived", True, False, "项目恢复"
    )
    db.commit()
    db.refresh(project)
    return project_detail(db, project)


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    """有引用（节点/依赖）的项目不允许物理删除，只能归档。"""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    if project.milestones:
        raise HTTPException(
            status_code=409,
            detail="项目下仍有节点，为不丢历史不允许删除，请改用归档",
        )
    assignments = db.execute(
        select(func.count()).select_from(Assignment).where(Assignment.project_id == project_id)
    ).scalar_one()
    if assignments:
        raise HTTPException(
            status_code=409,
            detail="项目仍有职责分配，为不丢历史不允许删除，请先解除职责或改用归档",
        )
    allocations = db.execute(
        select(func.count()).select_from(Allocation).where(Allocation.project_id == project_id)
    ).scalar_one()
    if allocations:
        raise HTTPException(
            status_code=409,
            detail="项目仍有周投入分配，为不丢历史不允许删除，请先删除分配或改用归档",
        )
    history_service.record(
        db, "project", project.id, project.name, "delete", "project", project.name, "", "删除空项目"
    )
    db.delete(project)
    db.commit()
    return {"deleted": project_id, "history_preserved": True}


# ------------------------------------------------------------------ 节点


@router.get("/projects/{project_id}/milestones", response_model=list[MilestoneOut])
def list_milestones(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return [milestone_out(db, m) for m in project.milestones]


@router.post("/projects/{project_id}/milestones", response_model=MilestoneOut, status_code=201)
def create_milestone(
    project_id: int, payload: MilestoneCreate, db: Session = Depends(get_db)
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    data = payload.model_dump()
    predecessor_ids = data.pop("predecessor_ids") or []
    for pid in predecessor_ids:
        pred = db.get(Milestone, pid)
        if pred is None or pred.project_id != project_id:
            raise HTTPException(status_code=400, detail="前置节点必须属于同一项目")
    milestone = Milestone(project_id=project_id, **data, edited_in_app=True)
    db.add(milestone)
    db.flush()
    for pid in predecessor_ids:
        db.add(MilestoneDependency(milestone_id=milestone.id, predecessor_id=pid))
    history_service.record(db, "milestone", milestone.id, milestone.name, "create")
    db.commit()
    db.refresh(milestone)
    return milestone_out(db, milestone)


@router.get("/milestones/{milestone_id}", response_model=MilestoneOut)
def get_milestone(milestone_id: int, db: Session = Depends(get_db)):
    milestone = db.get(Milestone, milestone_id)
    if milestone is None:
        raise HTTPException(status_code=404, detail="节点不存在")
    return milestone_out(db, milestone)


@router.patch("/milestones/{milestone_id}", response_model=MilestoneOut)
def update_milestone(
    milestone_id: int, payload: MilestoneUpdate, db: Session = Depends(get_db)
):
    milestone = db.get(Milestone, milestone_id)
    if milestone is None:
        raise HTTPException(status_code=404, detail="节点不存在")
    data = payload.model_dump(exclude_unset=True)
    predecessor_ids = data.pop("predecessor_ids", None)
    for field, value in data.items():
        old = getattr(milestone, field, None)
        if old != value:
            setattr(milestone, field, value)
            history_service.record(
                db,
                "milestone",
                milestone.id,
                milestone.name,
                "update",
                field,
                old if old is not None else "",
                value if value is not None else "",
                "节点信息更新",
            )
    if predecessor_ids is not None:
        _set_predecessors(db, milestone, predecessor_ids)
    milestone.edited_in_app = True
    milestone.version = (milestone.version or 1) + 1
    db.commit()
    db.refresh(milestone)
    return milestone_out(db, milestone)


def _set_predecessors(db: Session, milestone: Milestone, predecessor_ids: list[int]) -> None:
    for pid in predecessor_ids:
        pred = db.get(Milestone, pid)
        if pred is None or pred.project_id != milestone.project_id:
            raise HTTPException(status_code=400, detail="前置节点必须属于同一项目")
        if pred.id == milestone.id:
            raise HTTPException(status_code=400, detail="节点不能依赖自身")
    # 循环检测（前置 -> 后继）
    successor_map: dict[int, list[int]] = {}
    rows = db.execute(select(MilestoneDependency)).scalars().all()
    for dep in rows:
        successor_map.setdefault(dep.predecessor_id, []).append(dep.milestone_id)
    for pid in predecessor_ids:
        successor_map.setdefault(pid, [])
    successor_map.setdefault(milestone.id, [])
    for pid in predecessor_ids:
        if milestone.id not in successor_map[pid]:
            successor_map[pid].append(milestone.id)
    cycle = reschedule_service.detect_cycle(successor_map)
    if cycle:
        raise HTTPException(status_code=400, detail="依赖关系存在循环，整笔拒绝")
    db.query(MilestoneDependency).filter(
        MilestoneDependency.milestone_id == milestone.id
    ).delete()
    for pid in predecessor_ids:
        db.add(MilestoneDependency(milestone_id=milestone.id, predecessor_id=pid))
    db.flush()


@router.post("/milestones/{milestone_id}/archive", response_model=MilestoneOut)
def archive_milestone(milestone_id: int, db: Session = Depends(get_db)):
    milestone = db.get(Milestone, milestone_id)
    if milestone is None:
        raise HTTPException(status_code=404, detail="节点不存在")
    if not milestone.archived:
        milestone.archived = True
        milestone.edited_in_app = True
        milestone.version = (milestone.version or 1) + 1
        history_service.record(
            db, "milestone", milestone.id, milestone.name, "archive", "archived", False, True, "节点归档"
        )
        db.commit()
        db.refresh(milestone)
    return milestone_out(db, milestone)


@router.delete("/milestones/{milestone_id}")
def delete_milestone(milestone_id: int, db: Session = Depends(get_db)):
    milestone = db.get(Milestone, milestone_id)
    if milestone is None:
        raise HTTPException(status_code=404, detail="节点不存在")
    dependents = db.execute(
        select(func.count())
        .select_from(MilestoneDependency)
        .where(MilestoneDependency.predecessor_id == milestone_id)
    ).scalar_one()
    if dependents:
        raise HTTPException(
            status_code=409, detail="该节点被其它节点引用，为不丢历史不允许删除，请先解除依赖"
        )
    allocation_refs = db.execute(
        select(func.count())
        .select_from(Allocation)
        .where(Allocation.milestone_id == milestone_id)
    ).scalar_one()
    if allocation_refs:
        raise HTTPException(
            status_code=409,
            detail="该节点仍被周投入分配引用，为不丢历史不允许删除，请先删除相关分配",
        )
    history_service.record(
        db,
        "milestone",
        milestone.id,
        milestone.name,
        "delete",
        "milestone",
        milestone.name,
        "",
        "删除节点（历史保留）",
    )
    db.delete(milestone)
    db.commit()
    return {"deleted": milestone_id, "history_preserved": True}


# ------------------------------------------------------------------ 历史


@router.get("/history", response_model=list[HistoryOut])
def list_history(
    entity_type: str | None = None,
    entity_id: int | None = None,
    limit: int = Query(default=200, le=1000),
    db: Session = Depends(get_db),
):
    stmt = select(HistoryEntry).order_by(HistoryEntry.id.desc()).limit(limit)
    if entity_type:
        stmt = stmt.where(HistoryEntry.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(HistoryEntry.entity_id == entity_id)
    return db.execute(stmt).scalars().all()


# ------------------------------------------------------------------ 改期


@router.post("/reschedule/preview")
def reschedule_preview(payload: RescheduleRequest, db: Session = Depends(get_db)):
    try:
        return reschedule_service.create_preview(
            db,
            payload.milestone_id,
            payload.new_commit_date,
            payload.new_start_date,
            payload.mode,
        )
    except reschedule_service.RescheduleError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"message": exc.message, **exc.detail})


@router.post("/reschedule/apply")
def reschedule_apply(payload: RescheduleApply, db: Session = Depends(get_db)):
    try:
        return reschedule_service.apply_preview(db, payload.preview_id, payload.reason, payload.mode)
    except reschedule_service.RescheduleError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"message": exc.message, **exc.detail})


# ------------------------------------------------------------------ 验收样例


DEMO_PROJECT = "验收样例（菱形依赖）"


@router.post("/demo/seed", response_model=ProjectDetail)
def seed_demo(db: Session = Depends(get_db)):
    """建立验收样例：菱形依赖 A→B、A→C、B/C→D + 一个已完成节点。"""
    existing = db.execute(select(Project).where(Project.name == DEMO_PROJECT)).scalar_one_or_none()
    if existing is not None:
        return project_detail(db, existing)
    project = Project(name=DEMO_PROJECT, state="active", priority="P1", edited_in_app=True)
    db.add(project)
    db.flush()
    spec = [
        ("节点E（已完成）", "2026-11-02", "2026-11-05", "已完成", None),
        ("节点A", "2026-11-02", "2026-11-13", "进行中", None),
        ("节点B", "2026-11-16", "2026-11-20", "未开始", "节点A"),
        ("节点C", "2026-11-16", "2026-11-20", "未开始", "节点A"),
        ("节点D", "2026-11-23", "2026-11-27", "未开始", "节点B、节点C"),
    ]
    created: dict[str, Milestone] = {}
    for name, start, commit, state, _dep in spec:
        milestone = Milestone(
            project_id=project.id,
            name=name,
            deliverable=f"{name} 的交付物",
            start_date=date.fromisoformat(start),
            commit_date=date.fromisoformat(commit),
            state=state,
            buffer_source="内部",
            edited_in_app=True,
        )
        db.add(milestone)
        db.flush()
        created[name] = milestone
    for name, _s, _c, _st, dep in spec:
        if not dep:
            continue
        for pred_name in dep.split("、"):
            db.add(
                MilestoneDependency(
                    milestone_id=created[name].id, predecessor_id=created[pred_name].id
                )
            )
    history_service.record(db, "project", project.id, project.name, "create", reason="建立验收样例")
    db.commit()
    db.refresh(project)
    return project_detail(db, project)


# ------------------------------------------------------------------ E2：职责 / 容量 / 分配 / 核对
#
# 口径（首版计划）：
# - 周键必须是周一（Asia/Shanghai），覆盖周一至周日。
# - 只有 Allocation 计入占用；职责（Assignment）与节点执行人不计占用。
# - 容量来源：指定周覆盖 > 默认周容量；指定周显式未知不回退默认。
# - 未知 != 0：容量未知或投入未核对时不给精确剩余。
# - 分配一旦变动，该人员该周投入回到"待核对"。


def _require_week(week: date) -> date:
    if week.weekday() != 0:
        raise HTTPException(status_code=422, detail="周键必须是周一日期")
    return week


def _get_person(db: Session, person_id: int) -> Person:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="人员不存在")
    return person


def _get_project(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def _check_milestone(db: Session, milestone_id: int | None, project_id: int) -> None:
    """节点引用必须存在且属于同一项目，否则整笔拒绝。"""
    if milestone_id is None:
        return
    milestone = db.get(Milestone, milestone_id)
    if milestone is None:
        raise HTTPException(status_code=422, detail="节点不存在")
    if milestone.project_id != project_id:
        raise HTTPException(status_code=422, detail="节点必须属于同一项目")


def _derive_kind(milestone_id: int | None, requested: str | None) -> str:
    expected = "milestone" if milestone_id else "project_management"
    if requested and requested != expected:
        raise HTTPException(status_code=422, detail="分配类型与节点关联不一致")
    return expected


# ------------------------------------------------------------------ 人员周视图


@router.get("/persons/{person_id}/weeks/{week}", response_model=PersonWeekOut)
def get_person_week(person_id: int, week: date, db: Session = Depends(get_db)):
    person = _get_person(db, person_id)
    _require_week(week)
    return weekly_service.person_week(db, person, week)


@router.put("/persons/{person_id}/weeks/{week}/capacity", response_model=PersonWeekOut)
def set_person_week_capacity(
    person_id: int, week: date, payload: WeekCapacityUpdate, db: Session = Depends(get_db)
):
    """指定周容量覆盖。days 为 null 表示"显式未知"，不回退默认容量。"""
    person = _get_person(db, person_id)
    _require_week(week)
    if "days" not in payload.model_fields_set:
        raise HTTPException(status_code=422, detail="必须显式给出容量（数值或 null 表示未知）")
    row = db.execute(
        select(WeekCapacity).where(
            WeekCapacity.person_id == person_id, WeekCapacity.week == week
        )
    ).scalar_one_or_none()
    if row is None:
        row = WeekCapacity(person_id=person_id, week=week)
        db.add(row)
    row.days = payload.days
    row.note = payload.note
    db.commit()
    return weekly_service.person_week(db, person, week)


@router.delete("/persons/{person_id}/weeks/{week}/capacity", response_model=PersonWeekOut)
def delete_person_week_capacity(
    person_id: int, week: date, db: Session = Depends(get_db)
):
    """删除指定周覆盖后，回到默认周容量。"""
    person = _get_person(db, person_id)
    _require_week(week)
    row = db.execute(
        select(WeekCapacity).where(
            WeekCapacity.person_id == person_id, WeekCapacity.week == week
        )
    ).scalar_one_or_none()
    if row is not None:
        db.delete(row)
        db.commit()
    return weekly_service.person_week(db, person, week)


@router.put("/persons/{person_id}/weeks/{week}/review", response_model=PersonWeekOut)
def set_person_week_review(
    person_id: int, week: date, payload: WeekReviewUpdate, db: Session = Depends(get_db)
):
    """显式标记"本周投入已核对"。只有核对后才给精确剩余。"""
    person = _get_person(db, person_id)
    _require_week(week)
    row = db.execute(
        select(WeekReview).where(WeekReview.person_id == person_id, WeekReview.week == week)
    ).scalar_one_or_none()
    if row is None:
        row = WeekReview(person_id=person_id, week=week)
        db.add(row)
    row.reviewed = payload.reviewed
    db.commit()
    return weekly_service.person_week(db, person, week)


# ------------------------------------------------------------------ 项目职责


@router.get("/assignments", response_model=list[AssignmentOut])
def list_assignments(
    person_id: int | None = None,
    project_id: int | None = None,
    role: str | None = None,
    db: Session = Depends(get_db),
):
    stmt = select(Assignment).order_by(Assignment.id)
    if person_id is not None:
        stmt = stmt.where(Assignment.person_id == person_id)
    if project_id is not None:
        stmt = stmt.where(Assignment.project_id == project_id)
    if role is not None:
        stmt = stmt.where(Assignment.role == role)
    return [weekly_service.assignment_out(db, a) for a in db.execute(stmt).scalars().all()]


@router.post("/assignments", response_model=AssignmentOut, status_code=201)
def create_assignment(payload: AssignmentCreate, db: Session = Depends(get_db)):
    _get_person(db, payload.person_id)
    _get_project(db, payload.project_id)
    dup = db.execute(
        select(Assignment).where(
            Assignment.person_id == payload.person_id,
            Assignment.project_id == payload.project_id,
            Assignment.role == payload.role,
        )
    ).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=409, detail="该人员在此项目上已有同名职责")
    item = Assignment(
        person_id=payload.person_id,
        project_id=payload.project_id,
        role=payload.role,
        note=payload.note,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return weekly_service.assignment_out(db, item)


@router.patch("/assignments/{assignment_id}", response_model=AssignmentOut)
def update_assignment(
    assignment_id: int, payload: AssignmentUpdate, db: Session = Depends(get_db)
):
    item = db.get(Assignment, assignment_id)
    if item is None:
        raise HTTPException(status_code=404, detail="职责不存在")
    data = payload.model_dump(exclude_unset=True)
    role = data.get("role", item.role)
    if role != item.role:
        dup = db.execute(
            select(Assignment).where(
                Assignment.person_id == item.person_id,
                Assignment.project_id == item.project_id,
                Assignment.role == role,
                Assignment.id != item.id,
            )
        ).scalar_one_or_none()
        if dup:
            raise HTTPException(status_code=409, detail="该人员在此项目上已有同名职责")
    for field, value in data.items():
        setattr(item, field, "" if value is None and field == "note" else value)
    db.commit()
    db.refresh(item)
    return weekly_service.assignment_out(db, item)


@router.delete("/assignments/{assignment_id}")
def delete_assignment(assignment_id: int, db: Session = Depends(get_db)):
    item = db.get(Assignment, assignment_id)
    if item is None:
        raise HTTPException(status_code=404, detail="职责不存在")
    db.delete(item)
    db.commit()
    return {"deleted": assignment_id}


# ------------------------------------------------------------------ 周投入分配


@router.get("/allocations", response_model=list[AllocationOut])
def list_allocations(
    person_id: int | None = None,
    project_id: int | None = None,
    week: date | None = None,
    db: Session = Depends(get_db),
):
    """按人/项目/周筛选分配。筛选只影响视图，不改变占用口径。"""
    if week is not None:
        _require_week(week)
    items = weekly_service.list_allocations(db, person_id, project_id, week)
    return [weekly_service.allocation_out(db, a) for a in items]


@router.post("/allocations", response_model=AllocationOut, status_code=201)
def create_allocation(payload: AllocationCreate, db: Session = Depends(get_db)):
    _get_person(db, payload.person_id)
    _get_project(db, payload.project_id)
    _check_milestone(db, payload.milestone_id, payload.project_id)
    kind = _derive_kind(payload.milestone_id, payload.kind or None)
    item = Allocation(
        person_id=payload.person_id,
        project_id=payload.project_id,
        week=payload.week,
        days=payload.days,
        milestone_id=payload.milestone_id,
        kind=kind,
        note=payload.note,
    )
    db.add(item)
    db.flush()
    weekly_service.reset_review(db, payload.person_id, payload.week)
    db.commit()
    db.refresh(item)
    return weekly_service.allocation_out(db, item)


@router.patch("/allocations/{allocation_id}", response_model=AllocationOut)
def update_allocation(
    allocation_id: int, payload: AllocationUpdate, db: Session = Depends(get_db)
):
    item = db.get(Allocation, allocation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="分配不存在")
    data = payload.model_dump(exclude_unset=True)
    if "days" in data and data["days"] is None:
        raise HTTPException(status_code=422, detail="人天不能为空，未知请用 0 之外的方式表达")
    person_id = data.get("person_id", item.person_id)
    project_id = data.get("project_id", item.project_id)
    week = data.get("week", item.week)
    milestone_id = data["milestone_id"] if "milestone_id" in data else item.milestone_id
    _get_person(db, person_id)
    _get_project(db, project_id)
    _require_week(week)
    _check_milestone(db, milestone_id, project_id)
    kind = _derive_kind(milestone_id, data.get("kind", item.kind))
    old_person, old_week = item.person_id, item.week
    data.pop("kind", None)
    for field, value in data.items():
        setattr(item, field, value)
    item.kind = kind
    occupancy_changed = (
        item.person_id != old_person
        or item.week != old_week
        or item.milestone_id != milestone_id
        or item.days != payload.days
        or kind != item.kind
    )
    weekly_service.reset_review(db, old_person, old_week)
    if (item.person_id, item.week) != (old_person, old_week):
        weekly_service.reset_review(db, item.person_id, item.week)
    db.commit()
    db.refresh(item)
    return weekly_service.allocation_out(db, item)


@router.delete("/allocations/{allocation_id}")
def delete_allocation(allocation_id: int, db: Session = Depends(get_db)):
    item = db.get(Allocation, allocation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="分配不存在")
    person_id, week = item.person_id, item.week
    db.delete(item)
    weekly_service.reset_review(db, person_id, week)
    db.commit()
    return {"deleted": allocation_id}


# ------------------------------------------------------------------ E3 工作台


@router.get("/workbench", response_model=WorkbenchOut)
def get_workbench(
    week: date | None = None,
    project_id: int | None = None,
    owner_person_id: int | None = None,
    db: Session = Depends(get_db),
):
    """工作台汇总。只读；过滤只决定项目与人员范围，不裁剪人员占用与合计。"""
    selected = week if week is not None else weekly_service.current_week(
        workbench_service.today_shanghai()
    )
    _require_week(selected)
    return workbench_service.build_workbench(
        db, selected, project_id=project_id, owner_person_id=owner_person_id
    )
