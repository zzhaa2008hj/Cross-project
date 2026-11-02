from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import HistoryEntry


def record(
    db: Session,
    entity_type: str,
    entity_id: int,
    entity_name: str,
    action: str,
    field: str = "",
    old_value: object = "",
    new_value: object = "",
    reason: str = "",
    actor: str = "工程师B",
) -> HistoryEntry:
    entry = HistoryEntry(
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        action=action,
        field=field,
        old_value="" if old_value is None else str(old_value),
        new_value="" if new_value is None else str(new_value),
        reason=reason,
        actor=actor,
    )
    db.add(entry)
    return entry


def bump_version(milestone, db: Session) -> None:
    milestone.version = (milestone.version or 1) + 1
