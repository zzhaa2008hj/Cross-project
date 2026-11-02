"""依赖改期：预览 + 原子提交。

规则（首版计划）：
- 先预览传递依赖影响，再由 Hui 选择是否联动；一次提交记录旧日/新日/原因
- 按新旧承诺日的**日历日差**平移所有未完成、未取消的传递后继的已有开始日/承诺日
- 每个节点从预览快照只平移一次（菱形依赖不会叠加），空日期仍留空并提示
- 已完成/已取消节点只列受影响记录而不改动
- 跨项目依赖首版不支持
- 预览展示固定记录版本；提交时遇循环、版本已变、非法日期则整笔拒绝并刷新预览
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import TERMINAL_MILESTONE_STATES
from ..models import Milestone, MilestoneDependency, ReschedulePreview
from . import buffer as buffer_service
from . import history as history_service


class RescheduleError(Exception):
    def __init__(self, status_code: int, message: str, detail: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.detail = detail or {}


def _project_edges(db: Session, project_id: int) -> tuple[dict[int, list[int]], list[dict]]:
    """返回 (前��� -> 后继 映射, 跨项目依赖边列表)。"""
    rows = db.execute(
        select(MilestoneDependency, Milestone)
        .join(Milestone, Milestone.id == MilestoneDependency.milestone_id)
        .where(Milestone.project_id == project_id)
    ).all()
    successor_map: dict[int, list[int]] = {}
    for dep, _successor in rows:
        successor_map.setdefault(dep.predecessor_id, []).append(dep.milestone_id)
    for key in successor_map:
        successor_map[key].sort()

    cross_project: list[dict] = []
    all_deps = db.execute(select(MilestoneDependency)).scalars().all()
    milestone_ids = {d.milestone_id for d in all_deps} | {d.predecessor_id for d in all_deps}
    if milestone_ids:
        milestones = {
            m.id: m
            for m in db.execute(select(Milestone).where(Milestone.id.in_(milestone_ids))).scalars()
        }
        for dep in all_deps:
            succ = milestones.get(dep.milestone_id)
            pred = milestones.get(dep.predecessor_id)
            if succ is None or pred is None:
                continue
            if succ.project_id != pred.project_id:
                cross_project.append(
                    {
                        "milestone_id": succ.id,
                        "milestone_name": succ.name,
                        "predecessor_id": pred.id,
                        "predecessor_name": pred.name,
                        "project_a": succ.project_id,
                        "project_b": pred.project_id,
                    }
                )
    return successor_map, cross_project


def detect_cycle(successor_map: dict[int, list[int]]) -> list[int] | None:
    """在"前置 -> 后继"图上做 DFS，返回环上的节点 id（无环返回 None）。"""
    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[int, int] = {}
    stack: list[int] = []

    def visit(node: int) -> list[int] | None:
        color[node] = GREY
        stack.append(node)
        for nxt in successor_map.get(node, []):
            state = color.get(nxt, WHITE)
            if state == GREY:
                idx = stack.index(nxt)
                return stack[idx:] + [nxt]
            if state == WHITE:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for node in list(successor_map.keys()):
        if color.get(node, WHITE) == WHITE:
            found = visit(node)
            if found:
                return found
    return None


def _shift(value: date | None, delta: int) -> date | None:
    if value is None:
        return None
    return value + timedelta(days=delta)


def _milestone_payload(ms: Milestone) -> dict:
    return {
        "id": ms.id,
        "name": ms.name,
        "project_id": ms.project_id,
        "state": ms.state,
        "start_date": ms.start_date.isoformat() if ms.start_date else None,
        "commit_date": ms.commit_date.isoformat() if ms.commit_date else None,
        "version": ms.version,
        "assignee_id": ms.assignee_id,
    }


def build_preview(
    db: Session,
    milestone_id: int,
    new_commit_date: date | None,
    new_start_date: date | None,
    mode: str,
) -> dict:
    ms = db.get(Milestone, milestone_id)
    if ms is None:
        raise RescheduleError(404, "节点不存在")

    successor_map, cross_project = _project_edges(db, ms.project_id)
    if cross_project:
        raise RescheduleError(
            400, "跨项目依赖首版不支持，请先在软件内消除跨项目依赖", {"edges": cross_project}
        )

    cycle = detect_cycle(successor_map)
    if cycle:
        raise RescheduleError(400, "依赖关系存在循环，整笔拒绝", {"cycle": cycle})

    if new_commit_date is None and new_start_date is None:
        raise RescheduleError(400, "必须给出新的承诺日或开始日")

    delta = 0
    if new_commit_date is not None and ms.commit_date is not None:
        delta = (new_commit_date - ms.commit_date).days
    elif new_commit_date is not None and ms.commit_date is None:
        delta = 0

    # 目标节点的新日期
    target_commit = new_commit_date if new_commit_date is not None else ms.commit_date
    if new_start_date is not None:
        target_start = new_start_date
    elif delta and ms.start_date is not None:
        target_start = ms.start_date + timedelta(days=delta)
    else:
        target_start = ms.start_date

    changes: list[dict] = []
    affected_not_modified: list[dict] = []

    def add_change(old_ms, new_start, new_commit, note=""):
        changes.append(
            {
                "milestone_id": old_ms.id,
                "name": old_ms.name,
                "state": old_ms.state,
                "old_start_date": old_ms.start_date.isoformat() if old_ms.start_date else None,
                "old_commit_date": old_ms.commit_date.isoformat() if old_ms.commit_date else None,
                "new_start_date": new_start.isoformat() if new_start else None,
                "new_commit_date": new_commit.isoformat() if new_commit else None,
                "note": note,
            }
        )

    add_change(ms, target_start, target_commit)

    # 传递后继：每个节点从快照只平移一次
    successors: list[Milestone] = []
    if mode == "cascade":
        seen: set[int] = {ms.id}
        queue = [ms.id]
        while queue:
            current = queue.pop(0)
            for succ_id in successor_map.get(current, []):
                if succ_id in seen:
                    continue
                seen.add(succ_id)
                succ = db.get(Milestone, succ_id)
                if succ is None:
                    continue
                successors.append(succ)
                queue.append(succ_id)

    for succ in successors:
        if succ.state in TERMINAL_MILESTONE_STATES:
            affected_not_modified.append(
                {
                    "milestone_id": succ.id,
                    "name": succ.name,
                    "state": succ.state,
                    "reason": "已完成/已取消节点只列受影响记录，不改动",
                    "commit_date": succ.commit_date.isoformat() if succ.commit_date else None,
                }
            )
            continue
        if succ.start_date is None and succ.commit_date is None:
            affected_not_modified.append(
                {
                    "milestone_id": succ.id,
                    "name": succ.name,
                    "state": succ.state,
                    "reason": "该节点开始日与承诺日均为空，保持为空并提示",
                    "commit_date": None,
                }
            )
            continue
        note = ""
        if not delta:
            note = "承诺日未变，平移量为 0 天"
        new_start = _shift(succ.start_date, delta)
        new_commit = _shift(succ.commit_date, delta)
        if new_start is None:
            note = (note + "；" if note else "") + "开始日为空，保持为空"
        if new_commit is None:
            note = (note + "；" if note else "") + "承诺日为空，保持为空"
        add_change(succ, new_start, new_commit, note)

    versions = {str(c["milestone_id"]): _current_version(db, c["milestone_id"]) for c in changes}
    buffer_preview = buffer_service.derive_buffer(
        target_start, target_commit, ms.buffer_source, ms.workday_override
    )

    payload = {
        "milestone_id": ms.id,
        "milestone_name": ms.name,
        "project_id": ms.project_id,
        "mode": mode,
        "delta_days": delta,
        "old_commit_date": ms.commit_date.isoformat() if ms.commit_date else None,
        "new_commit_date": target_commit.isoformat() if target_commit else None,
        "old_start_date": ms.start_date.isoformat() if ms.start_date else None,
        "new_start_date": target_start.isoformat() if target_start else None,
        "changes": changes,
        "affected_not_modified": affected_not_modified,
        "buffer": buffer_preview,
        "successor_count": len(successors),
    }
    return {"payload": payload, "versions": versions}


def _current_version(db: Session, milestone_id: int) -> int:
    ms = db.get(Milestone, milestone_id)
    return ms.version if ms else -1


def create_preview(
    db: Session,
    milestone_id: int,
    new_commit_date: date | None,
    new_start_date: date | None,
    mode: str,
) -> dict:
    result = build_preview(db, milestone_id, new_commit_date, new_start_date, mode)
    row = ReschedulePreview(
        milestone_id=milestone_id,
        mode=mode,
        payload_json=json.dumps(result["payload"], ensure_ascii=False),
        versions_json=json.dumps(result["versions"], ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    payload = dict(result["payload"])
    payload["preview_id"] = row.id
    payload["versions"] = result["versions"]
    return payload


def apply_preview(db: Session, preview_id: int, reason: str, mode: str) -> dict:
    if not reason or not reason.strip():
        raise RescheduleError(400, "改期原因必填")

    row = db.get(ReschedulePreview, preview_id)
    if row is None:
        raise RescheduleError(404, "预览不存在，请重新预览")

    payload = json.loads(row.payload_json)
    stored_versions = json.loads(row.versions_json)

    # 模式一致性：联动提交必须基于联动预览（仅当前节点的预览不含后继）
    if mode == "cascade" and payload.get("mode") != "cascade":
        raise RescheduleError(
            400,
            "提交模式与预览模式不一致：联动改期需要重新生成联动预览",
            {"preview_mode": payload.get("mode"), "apply_mode": mode},
        )

    # 版本校验：任何一条记录被别人改过 -> 整笔拒绝并刷新预览
    current_versions = {k: _current_version(db, int(k)) for k in stored_versions}
    changed = {
        k: {"stored": stored_versions[k], "current": current_versions[k]}
        for k in stored_versions
        if stored_versions[k] != current_versions[k]
    }
    if changed:
        fresh = create_preview(
            db,
            row.milestone_id,
            date.fromisoformat(payload["new_commit_date"])
            if payload.get("new_commit_date")
            else None,
            date.fromisoformat(payload["new_start_date"]) if payload.get("new_start_date") else None,
            mode,
        )
        raise RescheduleError(
            409,
            "记录版本已变化，整笔拒绝，请基于刷新后的预览重新提交",
            {"changed": changed, "refreshed_preview": fresh},
        )

    # 重新校验循环与跨项目依赖
    ms = db.get(Milestone, row.milestone_id)
    if ms is None:
        raise RescheduleError(404, "节点不存在")
    successor_map, cross_project = _project_edges(db, ms.project_id)
    if cross_project:
        raise RescheduleError(400, "跨项目依赖首版不支持，整笔拒绝", {"edges": cross_project})
    if detect_cycle(successor_map):
        raise RescheduleError(400, "依赖关系存在循环，整笔拒绝")

    changes = payload["changes"]
    if mode == "current":
        changes = [c for c in changes if c["milestone_id"] == payload["milestone_id"]]
    else:
        # 联动：目标节点 + 传递后继
        changes = payload["changes"]

    # 非法日期校验
    for change in changes:
        new_start = date.fromisoformat(change["new_start_date"]) if change["new_start_date"] else None
        new_commit = (
            date.fromisoformat(change["new_commit_date"]) if change["new_commit_date"] else None
        )
        if new_start and new_commit and new_start > new_commit:
            raise RescheduleError(
                400,
                f"非法日期：节点「{change['name']}」开始日晚于承诺日，整笔拒绝",
                {"milestone_id": change["milestone_id"]},
            )

    updated: list[dict] = []
    try:
        for change in changes:
            target = db.get(Milestone, change["milestone_id"])
            if target is None:
                raise RescheduleError(404, "节点不存在，整笔拒绝")
            old_start = target.start_date
            old_commit = target.commit_date
            new_start = date.fromisoformat(change["new_start_date"]) if change["new_start_date"] else None
            new_commit = (
                date.fromisoformat(change["new_commit_date"]) if change["new_commit_date"] else None
            )
            if old_start != new_start:
                target.start_date = new_start
                history_service.record(
                    db,
                    "milestone",
                    target.id,
                    target.name,
                    "reschedule",
                    "start_date",
                    old_start.isoformat() if old_start else "",
                    new_start.isoformat() if new_start else "",
                    reason,
                )
            if old_commit != new_commit:
                target.commit_date = new_commit
                history_service.record(
                    db,
                    "milestone",
                    target.id,
                    target.name,
                    "reschedule",
                    "commit_date",
                    old_commit.isoformat() if old_commit else "",
                    new_commit.isoformat() if new_commit else "",
                    reason,
                )
            if old_start != new_start or old_commit != new_commit:
                target.version = (target.version or 1) + 1
                updated.append(
                    {
                        "milestone_id": target.id,
                        "name": target.name,
                        "old_start_date": old_start.isoformat() if old_start else None,
                        "old_commit_date": old_commit.isoformat() if old_commit else None,
                        "new_start_date": new_start.isoformat() if new_start else None,
                        "new_commit_date": new_commit.isoformat() if new_commit else None,
                    }
                )
        row.consumed = True
        db.commit()
    except RescheduleError:
        db.rollback()
        raise
    except Exception as exc:  # pragma: no cover - 兜底：整笔回滚
        db.rollback()
        raise RescheduleError(500, f"改期提交失败，已整笔回滚：{exc}") from exc

    return {
        "preview_id": preview_id,
        "mode": mode,
        "reason": reason,
        "updated": updated,
        "affected_not_modified": payload["affected_not_modified"],
        "buffer": buffer_service.derive_buffer(
            db.get(Milestone, payload["milestone_id"]).start_date,
            db.get(Milestone, payload["milestone_id"]).commit_date,
        ),
    }
