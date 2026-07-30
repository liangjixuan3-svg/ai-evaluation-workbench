from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.contracts import ConversationInput
from app.ingestion.models import Conversation


@dataclass(frozen=True)
class IngestionSummary:
    inserted: int
    skipped: int


def ingest_conversations(
    session: Session,
    source_id: str,
    items: list[ConversationInput],
    *,
    commit: bool = True,
) -> IngestionSummary:
    inserted = 0
    skipped = 0
    seen_external_ids: set[str] = set()
    try:
        for item in items:
            if item.external_id in seen_external_ids or _conversation_exists(
                session, source_id, item.external_id
            ):
                skipped += 1
                continue
            session.add(
                Conversation(
                    data_source_id=source_id,
                    external_id=item.external_id,
                    scenario=item.scenario,
                    status=item.status,
                    body=item.body,
                    occurred_at=item.occurred_at,
                )
            )
            seen_external_ids.add(item.external_id)
            inserted += 1
        if commit:
            session.commit()
        else:
            session.flush()
    except Exception:
        session.rollback()
        raise
    return IngestionSummary(inserted=inserted, skipped=skipped)


def _conversation_exists(session: Session, source_id: str, external_id: str) -> bool:
    return (
        session.scalar(
            select(Conversation.id).where(
                Conversation.data_source_id == source_id,
                Conversation.external_id == external_id,
            )
        )
        is not None
    )
