"""只读导入（vault -> 本项目 SQLite）。

边界：
- dry-run 不写库；报告每条来源定位、映射、跳过/失败理由
- 相同源快照重跑不增加重复记录（幂等）
- 源变化先显示差异，不覆盖软件已有编辑（edited_in_app 标记）
- 保留原日期/状态/历史原值；未知状态与坏日期不归为正常
- 只读打开源文件，绝不写 vault
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..models import ImportRun, Milestone, MilestoneDependency, Person, Project

MILESTONE_TABLE_HEADER = "| 项目 | 节点 | 交付物 | 开始日 | 承诺日 |"
MILESTONE_COLUMNS = [
    "项目",
    "节点",
    "交付物",
    "开始日",
    "承诺日",
    "工作日(覆盖)",
    "缓冲来源",
    "负责人",
    "本周投入",
    "依赖前置",
    "状态",
    "备注",
]

PROJECT_STATE_MAP = {
    "active": "active",
    "on-hold": "on-hold",
    "on_hold": "on-hold",
    "hold": "on-hold",
    "paused": "on-hold",
    "done": "done",
    "completed": "done",
    "closed": "done",
    "maintenance": "maintenance",
    "maintain": "maintenance",
}

EMPTY_DATE_TOKENS = {"", "待确认", "待定", "无", "-", "—", "tbd", "TBD", "n/a", "N/A"}
DEP_NONE_TOKENS = {"无", "无依赖", "-", "—", ""}


# ---------------------------------------------------------------- 基础工具


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_obj(obj: object) -> str:
    return _sha256_text(json.dumps(obj, ensure_ascii=False, sort_keys=True))


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", "", name or "")


def _strip_wikilink(text: str) -> str:
    value = (text or "").strip()
    match = re.match(r"^\[\[(.+?)\]\]$", value)
    if match:
        return match.group(1).strip()
    return value


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 YAML frontmatter（仅支持 key: value 简单形式）。"""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict = {}
    for line in parts[1].strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip().strip('"').strip("'")
        meta[key.strip()] = value
    return meta, parts[2]


def parse_date(raw: str) -> tuple[date | None, str]:
    """返回 (日期, 状态)。状态：ok | empty | invalid。"""
    value = (raw or "").strip()
    if value in EMPTY_DATE_TOKENS:
        return None, "empty"
    value = value.replace("/", "-")
    try:
        return date.fromisoformat(value[:10]), "ok"
    except ValueError:
        return None, "invalid"


def parse_percent(raw: str) -> float | None:
    value = (raw or "").strip().rstrip("%")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


# ---------------------------------------------------------------- 源解析


def _table_rows(text: str, header_prefix: str) -> list[tuple[int, list[str]]]:
    """找到以 header_prefix 开头的表头，返回 (行号, 单元格) 列表。"""
    lines = text.splitlines()
    rows: list[tuple[int, list[str]]] = []
    header_index = -1
    for idx, line in enumerate(lines):
        if line.startswith(header_prefix):
            header_index = idx
            break
    if header_index < 0:
        return rows
    for line in lines[header_index + 2 :]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            break
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        rows.append((header_index + 2 + (len(rows) + 1), cells))
    return rows


def _split_dependencies(raw: str) -> list[str]:
    value = (raw or "").strip()
    if value in DEP_NONE_TOKENS:
        return []
    parts = re.split(r"[、,，;；/]", value)
    return [p.strip() for p in parts if p.strip() and p.strip() not in DEP_NONE_TOKENS]


def parse_milestone_table(text: str, rel: str) -> list[dict]:
    """解析 20_项目/里程碑.md 的节点真源表。"""
    records: list[dict] = []
    for lineno, cells in _table_rows(text, MILESTONE_TABLE_HEADER):
        cells = cells + [""] * (len(MILESTONE_COLUMNS) - len(cells))
        row = dict(zip(MILESTONE_COLUMNS, cells[: len(MILESTONE_COLUMNS)]))
        project_name = _strip_wikilink(row["项目"])
        node_name = row["节点"].strip()
        source_ref = f"{rel}#L{lineno}"

        if not project_name or not node_name:
            records.append(
                {
                    "kind": "milestone",
                    "key": f"{project_name}::{node_name}",
                    "source_ref": source_ref,
                    "source_hash": _sha256_obj(row),
                    "values": {},
                    "mapping": {"项目": project_name, "节点": node_name},
                    "status": "fail",
                    "reason": "缺少项目名或节点名，无法建立唯一键",
                    "pending": [],
                }
            )
            continue

        pending: list[dict] = []
        status_text = row["状态"].strip()
        if status_text not in config.MILESTONE_STATES:
            records.append(
                {
                    "kind": "milestone",
                    "key": f"{project_name}::{node_name}",
                    "source_ref": source_ref,
                    "source_hash": _sha256_obj(row),
                    "values": {},
                    "mapping": {
                        "项目": project_name,
                        "节点": node_name,
                        "状态": status_text,
                        "原始状态": status_text,
                    },
                    "status": "fail",
                    "reason": f"状态值「{status_text}」不在六态内，未导入，需人工确认",
                    "pending": [
                        {
                            "ref": source_ref,
                            "field": "状态",
                            "raw": status_text,
                            "reason": "未知状态，不归为正常",
                        }
                    ],
                }
            )
            continue

        start_date, start_state = parse_date(row["开始日"])
        commit_date, commit_state = parse_date(row["承诺日"])
        bad_dates = []
        if start_state == "invalid":
            bad_dates.append(("开始日", row["开始日"].strip()))
        if commit_state == "invalid":
            bad_dates.append(("承诺日", row["承诺日"].strip()))
        if bad_dates:
            field, raw = bad_dates[0]
            records.append(
                {
                    "kind": "milestone",
                    "key": f"{project_name}::{node_name}",
                    "source_ref": source_ref,
                    "source_hash": _sha256_obj(row),
                    "values": {},
                    "mapping": {"项目": project_name, "节点": node_name, field: raw},
                    "status": "fail",
                    "reason": f"{field}「{raw}」无法解析为日期，未导入，需人工确认",
                    "pending": [
                        {
                            "ref": source_ref,
                            "field": field,
                            "raw": raw,
                            "reason": "坏日期，保留原值",
                        }
                    ],
                }
            )
            continue

        if start_state == "empty":
            pending.append(
                {
                    "ref": source_ref,
                    "field": "开始日",
                    "raw": row["开始日"].strip(),
                    "reason": "开始日待确认，按空值保留",
                }
            )
        if commit_state == "empty":
            pending.append(
                {
                    "ref": source_ref,
                    "field": "承诺日",
                    "raw": row["承诺日"].strip(),
                    "reason": "承诺日待确认，按空值保留",
                }
            )

        weekday_override = None
        override_raw = row["工作日(覆盖)"].strip()
        if override_raw:
            try:
                weekday_override = int(float(override_raw))
            except ValueError:
                pending.append(
                    {
                        "ref": source_ref,
                        "field": "工作日(覆盖)",
                        "raw": override_raw,
                        "reason": "覆盖工作日非数值，未采用",
                    }
                )

        percent = parse_percent(row["本周投入"])
        if percent is not None:
            pending.append(
                {
                    "ref": source_ref,
                    "field": "本周投入",
                    "raw": row["本周投入"].strip(),
                    "reason": "源为角色层百分比，E1 不折算到个人占用（E2 处理）",
                }
            )

        deps = _split_dependencies(row["依赖前置"])
        values = {
            "project_name": project_name,
            "name": node_name,
            "deliverable": row["交付物"].strip(),
            "start_date": start_date.isoformat() if start_date else None,
            "commit_date": commit_date.isoformat() if commit_date else None,
            "state": status_text,
            "owner_role": row["负责人"].strip(),
            "weekly_investment_pct": percent,
            "buffer_source": row["缓冲来源"].strip() or None,
            "workday_override": weekday_override,
            "note": row["备注"].strip(),
            "assignee_id": None,
            "progress": "",
            "blocker_reason": "",
            "contact_person": "",
            "next_followup_date": None,
            "dependencies": deps,
        }
        mapping = {
            "项目": project_name,
            "节点": node_name,
            "交付物": "deliverable",
            "开始日": "start_date",
            "承诺日": "commit_date",
            "状态": "state",
            "负责人(角色层)": "owner_role",
            "缓冲来源": "buffer_source",
            "依赖前置": "dependencies",
            "备注": "note",
        }
        pending.append(
            {
                "ref": source_ref,
                "field": "执行人",
                "raw": "",
                "reason": "源只记录角色层负责人，未指派具体执行人（未分派）",
            }
        )
        records.append(
            {
                "kind": "milestone",
                "key": f"{project_name}::{node_name}",
                "source_ref": source_ref,
                "source_hash": _sha256_obj(values),
                "values": values,
                "mapping": mapping,
                "status": "import",
                "reason": "",
                "pending": pending,
            }
        )
    return records


def parse_personnel(text: str, rel: str) -> list[dict]:
    """解析 99_系统/人员.md 的角色花名册与已知人名映射。"""
    records: list[dict] = []
    roles: list[str] = []
    for lineno, cells in _table_rows(text, "| 角色 | 可用产能 |"):
        if len(cells) < 1:
            continue
        role = cells[0].strip()
        if role:
            roles.append(role)

    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        match = re.match(r"^(?:>\s*)?[-*]\s*([一-鿿]{2,4})\s*→\s*(.+)$", stripped)
        if not match:
            continue
        name = match.group(1)
        description = match.group(2).strip().replace("**", "")
        person_roles = [r for r in roles if r in description]
        records.append(
            {
                "kind": "person",
                "key": name,
                "source_ref": f"{rel}#L{lineno}",
                "source_hash": _sha256_text(f"{name}|{description}"),
                "values": {
                    "name": name,
                    "roles": "/".join(person_roles),
                    "note": description,
                    "weekly_capacity": None,
                },
                "mapping": {"人名": "name", "角色": "roles", "说明": "note"},
                "status": "import",
                "reason": "",
                "pending": [
                    {
                        "ref": f"{rel}#L{lineno}",
                        "field": "周可用人天",
                        "raw": "",
                        "reason": "源只有角色层百分比产能，人员容量属 E2，暂留未知",
                    }
                ],
            }
        )

    return records


def product_role_person_records(existing: list[dict]) -> list[dict]:
    """北京仓储产品口径人员（李冠男负责人 / 郑伊平执行 / 赵辉辉统筹）。

    仅在快照含北京仓储项目时追加；vault 源已记录的人名不重复添加。
    """
    records: list[dict] = []
    for role, name in config.BEIJING_WAREHOUSE_ROLES.items():
        role_desc = f"{role}（产品确认口径）"
        if any(r["key"] == name for r in existing):
            continue
        records.append(
            {
                "kind": "person",
                "key": name,
                "source_ref": "产品约定(HUI-203 首版计划)",
                "source_hash": _sha256_text(f"{name}|{role_desc}|产品约定"),
                "values": {
                    "name": name,
                    "roles": role_desc,
                    "note": "北京仓储新口径（产品确认），vault 源未记录",
                    "weekly_capacity": None,
                },
                "mapping": {"人名": "name", "北京仓储口径": "roles"},
                "status": "import",
                "reason": "",
                "pending": [
                    {
                        "ref": "产品约定(HUI-203 首版计划)",
                        "field": "北京仓储口径",
                        "raw": role_desc,
                        "reason": "vault 源仅记录角色层负责人，该口径来自产品约定，未自动指派节点执行人",
                    }
                ],
            }
        )
    return records


def parse_project_notes(vault_root: Path, rel_dir: str) -> tuple[list[dict], list[str]]:
    """扫描项目笔记 frontmatter 与进展区。"""
    records: list[dict] = []
    sources: list[str] = []
    base = vault_root / rel_dir
    if not base.exists():
        return records, sources
    for path in sorted(base.rglob("*.md")):
        rel = str(path.relative_to(vault_root))
        sources.append(rel)
        text = path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)
        if meta.get("type") != "project":
            continue
        title = (meta.get("title") or path.stem).strip()
        raw_status = (meta.get("status") or "").strip()
        priority = (meta.get("priority") or "").strip()
        state = PROJECT_STATE_MAP.get(raw_status.lower())
        progress_text = ""
        match = re.search(r"^##\s*进展\s*$", body, re.MULTILINE)
        if match:
            tail = body[match.end() :]
            next_heading = re.search(r"^##\s", tail, re.MULTILINE)
            section = tail[: next_heading.start()] if next_heading else tail
            progress_text = section.strip()
        pending: list[dict] = []
        if state is None:
            pending.append(
                {
                    "ref": rel,
                    "field": "status",
                    "raw": raw_status,
                    "reason": "项目状态未知，未映射到四态，需人工确认",
                }
            )
        values = {
            "name": title,
            "state": state,
            "raw_state": raw_status,
            "priority": priority,
            "progress": progress_text,
            "note": "",
        }
        if "北京仓储" in title:
            pending.append(
                {
                    "ref": rel,
                    "field": "负责人口径",
                    "raw": "李冠男/郑伊平/赵辉辉",
                    "reason": (
                        "产品确认口径：北京仓储负责人李冠男、执行郑伊平、统筹赵辉辉；"
                        "vault 源只记录角色层，未自动指派节点执行人"
                    ),
                }
            )
        records.append(
            {
                "kind": "project",
                "key": title,
                "source_ref": rel,
                "source_hash": _sha256_obj(values),
                "values": values,
                "mapping": {
                    "title": "name",
                    "status": "state",
                    "priority": "priority",
                    "进展": "progress",
                },
                "status": "import" if state else "import",
                "reason": "" if state else "项目状态未知，已按 active 建档并在待确认清单列出",
                "pending": pending,
            }
        )
    return records, sources


# ---------------------------------------------------------------- 快照


def build_snapshot(vault_root: Path | None = None) -> dict:
    """读取只读来源，生成快照（不写库）。"""
    root = vault_root or config.vault_dir()
    sources: list[dict] = []
    records: list[dict] = []

    ms_path = root / config.MILESTONE_SOURCE_REL
    if ms_path.exists():
        text = ms_path.read_text(encoding="utf-8")
        sources.append(_source_entry(root, ms_path, text))
        records.extend(parse_milestone_table(text, config.MILESTONE_SOURCE_REL))
    else:
        sources.append(
            {
                "rel": config.MILESTONE_SOURCE_REL,
                "sha256": "",
                "bytes": 0,
                "lines": 0,
                "exists": False,
            }
        )

    person_path = root / config.PERSONNEL_SOURCE_REL
    if person_path.exists():
        text = person_path.read_text(encoding="utf-8")
        sources.append(_source_entry(root, person_path, text))
        records.extend(parse_personnel(text, config.PERSONNEL_SOURCE_REL))
    else:
        sources.append(
            {
                "rel": config.PERSONNEL_SOURCE_REL,
                "sha256": "",
                "bytes": 0,
                "lines": 0,
                "exists": False,
            }
        )

    note_records, note_sources = parse_project_notes(root, config.PROJECT_NOTES_DIR_REL)
    for rel in note_sources:
        path = root / rel
        text = path.read_text(encoding="utf-8")
        sources.append(_source_entry(root, path, text))
    records.extend(note_records)

    # 北京仓储产品口径人员：仅当快照含北京仓储项目时补充
    if any(r["kind"] == "project" and "北京仓储" in r["key"] for r in records):
        records.extend(product_role_person_records([r for r in records if r["kind"] == "person"]))

    # 项目合并：里程碑表里的项目名也要成为 project 记录
    existing_project_keys = {_norm_name(r["key"]) for r in records if r["kind"] == "project"}
    for record in records:
        if record["kind"] != "milestone":
            continue
        name = record["values"].get("project_name") or ""
        if not name or _norm_name(name) in existing_project_keys:
            continue
        existing_project_keys.add(_norm_name(name))
        records.append(
            {
                "kind": "project",
                "key": name,
                "source_ref": record["source_ref"],
                "source_hash": _sha256_obj({"name": name, "from": "milestone_table"}),
                "values": {
                    "name": name,
                    "state": "active",
                    "raw_state": "",
                    "priority": "",
                    "progress": "",
                    "note": "由里程碑表推导，无对应项目笔记 frontmatter",
                },
                "mapping": {"项目": "name"},
                "status": "import",
                "reason": "",
                "pending": [
                    {
                        "ref": record["source_ref"],
                        "field": "status",
                        "raw": "",
                        "reason": "未找到项目笔记 frontmatter，状态默认 active，需人工确认",
                    }
                ],
            }
        )

    sources.sort(key=lambda s: s["rel"])
    snapshot_hash = _sha256_obj([[s["rel"], s["sha256"]] for s in sources])
    return {"sources": sources, "records": records, "snapshot_hash": snapshot_hash}


def _source_entry(root: Path, path: Path, text: str) -> dict:
    return {
        "rel": str(path.relative_to(root)),
        "sha256": _sha256_text(text),
        "bytes": len(text.encode("utf-8")),
        "lines": len(text.splitlines()),
        "exists": True,
    }


# ---------------------------------------------------------------- 差异与应用


def _diff(existing: dict, incoming: dict, fields: list[str]) -> list[dict]:
    """字段差异。键名与前端契约一致：old_value / new_value。"""
    diffs: list[dict] = []
    for field in fields:
        old = existing.get(field)
        new = incoming.get(field)
        if str(old) != str(new):
            diffs.append({"field": field, "old_value": old, "new_value": new})
    return diffs


def _locate_diffs(diffs: list[dict], record: dict) -> list[dict]:
    """给每条差异补上来源定位（kind/key/source_ref），前端可直接定位到对象。"""
    key = record.get("key") or record.get("values", {}).get("name") or ""
    for diff in diffs:
        diff.setdefault("kind", record["kind"])
        diff.setdefault("key", key)
        diff.setdefault("source_ref", record.get("source_ref") or "")
    return diffs


def _project_values(record: dict) -> dict:
    values = record["values"]
    return {
        "name": values["name"],
        "state": values.get("state") or "active",
        "priority": values.get("priority") or "",
        "progress": values.get("progress") or "",
        "note": values.get("note") or "",
    }


def _find_project(db: Session, name: str) -> Project | None:
    rows = db.execute(select(Project)).scalars().all()
    target = _norm_name(name)
    for row in rows:
        if _norm_name(row.name) == target:
            return row
    return None


def _find_milestone(db: Session, project: Project, name: str) -> Milestone | None:
    """按项目 + 规范化名称查节点。

    直接查库而不是走 project.milestones 关系，避免同一次导入中新建节点
    因关系缓存过期而查不到（菱形/链式依赖会因此丢失）。
    """
    target = _norm_name(name)
    rows = db.execute(
        select(Milestone).where(Milestone.project_id == project.id)
    ).scalars().all()
    for row in rows:
        if _norm_name(row.name) == target:
            return row
    return None


def apply_snapshot(db: Session, snapshot: dict, dry: bool = False) -> dict:
    """把快照写入库；返回报告数据。幂等：相同快照重跑不产生重复记录。

    dry=True 时不提交，由调用方回滚，保证试运行不写库。
    """
    records = snapshot["records"]
    record_reports: list[dict] = []
    pending_all: list[dict] = []
    diffs_all: list[dict] = []
    imported = skipped = failed = 0

    person_cache: dict[str, Person] = {
        p.name: p for p in db.execute(select(Person)).scalars().all()
    }

    # 1) 人员
    for record in records:
        if record["kind"] != "person":
            continue
        report = _apply_person(db, record, person_cache)
        record_reports.append(report)
        pending_all.extend(record["pending"])
        if report["status"] == "import":
            imported += 1
        elif report["status"] == "skip":
            skipped += 1
        else:
            failed += 1

    # 2) 项目
    project_cache: dict[str, Project] = {}
    for record in records:
        if record["kind"] != "project":
            continue
        report = _apply_project(db, record, project_cache)
        record_reports.append(report)
        pending_all.extend(record["pending"])
        diffs_all.extend(_locate_diffs(report.get("diff") or [], record))
        if report["status"] == "import":
            imported += 1
        elif report["status"] == "skip":
            skipped += 1
        else:
            failed += 1

    # 3) 节点（先全部建档/更新）
    milestone_reports: list[tuple[dict, dict]] = []
    for record in records:
        if record["kind"] != "milestone":
            continue
        if record.get("status") == "fail":
            # 解析阶段已判定失败（未知状态/坏日期）：不写库，原值进待确认
            report = {
                "kind": "milestone",
                "key": record["key"],
                "source_ref": record["source_ref"],
                "source_hash": record["source_hash"],
                "mapping": record["mapping"],
                "status": "fail",
                "reason": record.get("reason", ""),
                "pending": list(record["pending"]),
                "diff": [],
            }
        else:
            report = _apply_milestone(db, record, project_cache, person_cache)
        record_reports.append(report)
        pending_all.extend(report["pending"])
        diffs_all.extend(_locate_diffs(report.get("diff") or [], record))
        milestone_reports.append((record, report))
        if report["status"] == "import":
            imported += 1
        elif report["status"] == "skip":
            skipped += 1
        else:
            failed += 1

    # 4) 依赖：所有节点建档完成后再连边，避免源表顺序导致依赖丢失
    for record, report in milestone_reports:
        if report.get("status") == "fail":
            continue
        milestone_id = report.get("milestone_id")
        if not milestone_id:
            continue
        milestone = db.get(Milestone, milestone_id)
        if milestone is None:
            continue
        project = db.get(Project, milestone.project_id)
        if project is None:
            continue
        dep_report = _apply_dependencies(
            db, milestone, record["values"].get("dependencies") or [], project
        )
        report["pending"] = list(report["pending"]) + dep_report["pending"]
        pending_all.extend(dep_report["pending"])

    if not dry:
        db.commit()
    totals = _collect_totals(db)
    return {
        "records": record_reports,
        "pending": pending_all,
        "diffs": diffs_all,
        "counts": {"read": len(record_reports), "imported": imported, "skipped": skipped, "failed": failed},
        "totals": totals,
    }


def _collect_totals(db: Session) -> dict:
    """统计当前会话（含未提交的新增）里的项目/节点/维护期项目数量。"""
    projects = {p.id: p for p in db.execute(select(Project)).scalars().all()}
    milestones = db.execute(select(Milestone)).scalars().all()
    for obj in db.new:
        if isinstance(obj, Project):
            projects[obj.id] = obj
        elif isinstance(obj, Milestone):
            milestones.append(obj)
    return {
        "milestones": len(milestones),
        "projects": len(projects),
        "maintenance_projects": sum(1 for p in projects.values() if p.state == "maintenance"),
    }


def dry_run_snapshot(db: Session, snapshot: dict) -> dict:
    """试运行：完整走一遍分类逻辑但不落库（结束时整体回滚）。"""
    result = apply_snapshot(db, snapshot, dry=True)
    db.rollback()
    return result


def _apply_person(db: Session, record: dict, cache: dict[str, Person]) -> dict:
    values = record["values"]
    name = values["name"]
    existing = cache.get(name)
    base = {
        "kind": "person",
        "source_ref": record["source_ref"],
        "source_hash": record["source_hash"],
        "mapping": record["mapping"],
        "pending": [],
        "diff": [],
    }
    if existing is None:
        person = Person(
            name=name,
            roles=values.get("roles") or "",
            note=values.get("note") or "",
            weekly_capacity=values.get("weekly_capacity"),
            source_ref=record["source_ref"],
            source_record_hash=record["source_hash"],
        )
        db.add(person)
        db.flush()
        cache[name] = person
        return {**base, "status": "import", "reason": "新建人员记录"}
    if existing.source_record_hash == record["source_hash"]:
        return {**base, "status": "skip", "reason": "与已导入快照一致（幂等，不重复写入）"}
    diff = _diff(
        {"roles": existing.roles, "note": existing.note},
        {"roles": values.get("roles") or "", "note": values.get("note") or ""},
        ["roles", "note"],
    )
    if existing.edited_in_app:
        return {
            **base,
            "status": "skip",
            "reason": "软件内已有编辑，不覆盖；差异见 diff",
            "diff": diff,
            "pending": [
                {
                    "ref": record["source_ref"],
                    "field": "人员",
                    "raw": name,
                    "reason": "源已变化但软件内有编辑，保留软件值待人工确认",
                }
            ],
        }
    existing.roles = values.get("roles") or ""
    existing.note = values.get("note") or ""
    existing.source_record_hash = record["source_hash"]
    existing.source_ref = record["source_ref"]
    return {**base, "status": "import", "reason": "源变化，已更新（此前无软件内编辑）", "diff": diff}


def _apply_project(
    db: Session, record: dict, cache: dict[str, Project]
) -> dict:
    values = record["values"]
    name = values["name"]
    existing = cache.get(name) or _find_project(db, name)
    base = {
        "kind": "project",
        "source_ref": record["source_ref"],
        "source_hash": record["source_hash"],
        "mapping": record["mapping"],
        "pending": [],
        "diff": [],
    }
    target_values = _project_values(record)
    if existing is None:
        project = Project(
            name=target_values["name"],
            state=target_values["state"],
            priority=target_values["priority"],
            progress=target_values["progress"],
            note=target_values["note"],
            source_ref=record["source_ref"],
            source_record_hash=record["source_hash"],
        )
        db.add(project)
        db.flush()
        cache[name] = project
        return {**base, "status": "import", "reason": "新建项目记录"}
    if existing.source_record_hash == record["source_hash"]:
        return {**base, "status": "skip", "reason": "与已导入快照一致（幂等，不重复写入）"}
    diff = _diff(
        {"state": existing.state, "priority": existing.priority, "progress": existing.progress},
        target_values,
        ["state", "priority", "progress"],
    )
    if existing.edited_in_app:
        return {
            **base,
            "status": "skip",
            "reason": "软件内已有编辑，不覆盖；差异见 diff",
            "diff": diff,
            "pending": [
                {
                    "ref": record["source_ref"],
                    "field": "项目",
                    "raw": name,
                    "reason": "源已变化但软件内有编辑，保留软件值待人工确认",
                }
            ],
        }
    existing.state = target_values["state"]
    existing.priority = target_values["priority"]
    existing.progress = target_values["progress"]
    existing.source_record_hash = record["source_hash"]
    existing.source_ref = record["source_ref"]
    return {**base, "status": "import", "reason": "源变化，已更新（此前无软件内编辑）", "diff": diff}


def _apply_milestone(
    db: Session,
    record: dict,
    project_cache: dict[str, Project],
    person_cache: dict[str, Person],
) -> dict:
    values = record["values"]
    project_name = values["project_name"]
    base = {
        "kind": "milestone",
        "source_ref": record["source_ref"],
        "source_hash": record["source_hash"],
        "mapping": record["mapping"],
        "pending": [],
        "diff": [],
    }
    project = project_cache.get(project_name) or _find_project(db, project_name)
    if project is None:
        project = Project(
            name=project_name,
            state="active",
            source_ref=record["source_ref"],
            source_record_hash=_sha256_obj({"name": project_name, "from": "milestone_table"}),
        )
        db.add(project)
        db.flush()
        project_cache[project_name] = project

    existing = _find_milestone(db, project, values["name"])
    incoming = {
        "deliverable": values["deliverable"],
        "start_date": values["start_date"],
        "commit_date": values["commit_date"],
        "state": values["state"],
        "owner_role": values["owner_role"],
        "weekly_investment_pct": values["weekly_investment_pct"],
        "buffer_source": values["buffer_source"],
        "workday_override": values["workday_override"],
        "note": values["note"],
    }
    if existing is None:
        milestone = Milestone(
            project_id=project.id,
            name=values["name"],
            deliverable=incoming["deliverable"],
            start_date=_to_date(incoming["start_date"]),
            commit_date=_to_date(incoming["commit_date"]),
            state=incoming["state"],
            owner_role=incoming["owner_role"],
            weekly_investment_pct=incoming["weekly_investment_pct"],
            buffer_source=incoming["buffer_source"],
            workday_override=incoming["workday_override"],
            note=incoming["note"],
            source_ref=record["source_ref"],
            source_record_hash=record["source_hash"],
        )
        db.add(milestone)
        db.flush()
        base["pending"] = list(record["pending"])
        return {
            **base,
            "status": "import",
            "reason": "新建节点记录",
            "pending": base["pending"],
            "milestone_id": milestone.id,
        }

    if existing.source_record_hash == record["source_hash"]:
        return {
            **base,
            "status": "skip",
            "reason": "与已导入快照一致（幂等，不重复写入）",
            "milestone_id": existing.id,
        }

    diff = _diff(
        {
            "deliverable": existing.deliverable,
            "start_date": existing.start_date.isoformat() if existing.start_date else None,
            "commit_date": existing.commit_date.isoformat() if existing.commit_date else None,
            "state": existing.state,
            "owner_role": existing.owner_role,
            "weekly_investment_pct": existing.weekly_investment_pct,
            "buffer_source": existing.buffer_source,
            "workday_override": existing.workday_override,
            "note": existing.note,
        },
        incoming,
        list(incoming.keys()),
    )
    if existing.edited_in_app:
        return {
            **base,
            "status": "skip",
            "reason": "软件内已有编辑，不覆盖；差异见 diff",
            "diff": diff,
            "pending": list(record["pending"])
            + [
                {
                    "ref": record["source_ref"],
                    "field": "节点",
                    "raw": values["name"],
                    "reason": "源已变化但软件内有编辑，保留软件值待人工确认",
                }
            ],
        }
    existing.deliverable = incoming["deliverable"]
    existing.start_date = _to_date(incoming["start_date"])
    existing.commit_date = _to_date(incoming["commit_date"])
    existing.state = incoming["state"]
    existing.owner_role = incoming["owner_role"]
    existing.weekly_investment_pct = incoming["weekly_investment_pct"]
    existing.buffer_source = incoming["buffer_source"]
    existing.workday_override = incoming["workday_override"]
    existing.note = incoming["note"]
    existing.source_record_hash = record["source_hash"]
    existing.source_ref = record["source_ref"]
    # 导入更新也算一次改动：版本递增，旧改期预览随即失效，避免用旧预览覆盖新导入的日期
    existing.version = (existing.version or 1) + 1
    return {
        **base,
        "status": "import",
        "reason": "源变化，已更新（此前无软件内编辑）",
        "diff": diff,
        "pending": list(record["pending"]),
        "milestone_id": existing.id,
    }


def _to_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _apply_dependencies(
    db: Session, milestone: Milestone, deps: list[str], project: Project
) -> dict:
    """按源声明补依赖。

    只补「源里新出现」的依赖边：源里声明过、但用户已在软件内删掉的边不再复活。
    判定依据是 Milestone.source_dep_names（上次导入时源声明过的前置名）。
    """
    pending: list[dict] = []
    declared = [str(d).strip() for d in deps if str(d).strip()]
    try:
        previous = set(json.loads(milestone.source_dep_names or "[]"))
    except (TypeError, ValueError):
        previous = set()
    existing_pred = {d.predecessor_id for d in milestone.dependencies}
    for dep_name in declared:
        target = _find_milestone(db, project, dep_name)
        if target is None:
            pending.append(
                {
                    "ref": milestone.source_ref or "",
                    "field": "依赖前置",
                    "raw": dep_name,
                    "reason": "依赖项在本项目内无法解析为节点，未建立依赖",
                }
            )
            continue
        if target.id == milestone.id:
            continue
        if target.id in existing_pred:
            continue
        if dep_name in previous:
            # 源里声明过、用户已删除：不复活
            continue
        db.add(
            MilestoneDependency(
                milestone_id=milestone.id, predecessor_id=target.id, source_ref=milestone.source_ref
            )
        )
        existing_pred.add(target.id)
    milestone.source_dep_names = json.dumps(sorted(set(declared)), ensure_ascii=False)
    return {"pending": pending}


# ---------------------------------------------------------------- 报告


def build_report(
    db: Session,
    snapshot: dict,
    applied: bool,
    records: list[dict],
    pending: list[dict],
    diffs: list[dict],
    counts: dict,
    totals: dict | None = None,
) -> dict:
    totals = totals or _collect_totals(db)
    reconciliation = {
        "expected_milestone_count": config.EXPECTED_MILESTONE_COUNT,
        "actual_milestone_count": totals["milestones"],
        "expected_maintenance_project_count": config.EXPECTED_MAINTENANCE_PROJECT_COUNT,
        "actual_maintenance_project_count": totals["maintenance_projects"],
        "actual_tracked_project_count": totals["projects"],
        "note": (
            "对账预期来自首版方案：35 节点、7 个维护期项目。"
            "实际以 vault 真源表与项目笔记 frontmatter 为准，差异在此说明，不做静默修正。"
        ),
    }
    return {
        "snapshot_hash": snapshot["snapshot_hash"],
        "sources": snapshot["sources"],
        "records": records,
        "pending": pending,
        "diffs": diffs,
        "counts": counts,
        "reconciliation": reconciliation,
    }


def render_markdown(report: dict, applied: bool) -> str:
    counts = report["counts"]
    lines: list[str] = []
    lines.append("# 导入报告")
    lines.append("")
    lines.append(f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}")
    lines.append(f"- 模式：{'已导入库（apply）' if applied else '试运行（dry-run，不写库）'}")
    lines.append(f"- 源快照哈希：{report['snapshot_hash']}")
    lines.append(
        f"- 读入 {counts['read']} / 导入 {counts['imported']} / 跳过 {counts['skipped']} / 失败 {counts['failed']}"
        f"（读入 = 导入 + 跳过 + 失败，各互斥）"
    )
    lines.append("")
    lines.append("## 来源与校验值")
    lines.append("")
    lines.append("| 来源文件 | SHA256 | 字节 | 行数 |")
    lines.append("|---|---|---|---|")
    for src in report["sources"]:
        lines.append(
            f"| `{src['rel']}` | `{src['sha256'][:16]}…` | {src['bytes']} | {src['lines']} |"
        )
    lines.append("")
    lines.append("## 逐条记录")
    lines.append("")
    lines.append("| 类型 | 来源定位 | 状态 | 原因 | 映射 |")
    lines.append("|---|---|---|---|---|")
    for rec in report["records"]:
        mapping = "；".join(f"{k}→{v}" for k, v in (rec.get("mapping") or {}).items())
        lines.append(
            f"| {rec['kind']} | `{rec['source_ref']}` | {rec['status']} | {rec.get('reason','')} | {mapping} |"
        )
    lines.append("")
    lines.append("## 待确认清单")
    lines.append("")
    if not report["pending"]:
        lines.append("（无）")
    else:
        lines.append("| 来源定位 | 字段 | 原始值 | 原因 |")
        lines.append("|---|---|---|---|")
        for item in report["pending"]:
            lines.append(
                f"| `{item.get('ref','')}` | {item.get('field','')} | {item.get('raw','')} | {item.get('reason','')} |"
            )
    lines.append("")
    lines.append("## 差异")
    lines.append("")
    if not report["diffs"]:
        lines.append("（无）")
    else:
        for diff in report["diffs"]:
            lines.append(
                f"- `{diff.get('kind','')}` `{diff.get('key','')}` 字段 `{diff.get('field','')}`：`{diff.get('old')}` → `{diff.get('new')}`"
            )
    lines.append("")
    lines.append("## 对账")
    lines.append("")
    rec = report["reconciliation"]
    lines.append(
        f"- 节点：预期 {rec['expected_milestone_count']}，实际 {rec['actual_milestone_count']}"
    )
    lines.append(
        f"- 维护期项目：预期 {rec['expected_maintenance_project_count']}，实际 {rec['actual_maintenance_project_count']}"
    )
    lines.append(f"- 纳入管理的项目总数：{rec['actual_tracked_project_count']}")
    lines.append(f"- 说明：{rec['note']}")
    lines.append("")
    return "\n".join(lines)


def save_import_run(db: Session, report: dict, applied: bool, markdown: str) -> ImportRun:
    counts = report["counts"]
    run = ImportRun(
        snapshot_hash=report["snapshot_hash"],
        mode="apply" if applied else "dry_run",
        read_count=counts["read"],
        imported_count=counts["imported"],
        skipped_count=counts["skipped"],
        failed_count=counts["failed"],
        report_json=json.dumps(report, ensure_ascii=False),
        report_markdown=markdown,
        applied=applied,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run
