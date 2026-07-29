from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base
from app.shared.types import MYSQL_TABLE_ARGS, UTCDateTime, utc_now, uuid_primary_key


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = MYSQL_TABLE_ARGS

    id: Mapped[str] = uuid_primary_key()
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)


def record_audit(
    session: Session,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
) -> AuditEvent:
    event = AuditEvent(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
    )
    session.add(event)
    session.flush()
    return event
