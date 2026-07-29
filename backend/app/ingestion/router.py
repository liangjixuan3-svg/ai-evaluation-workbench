from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_session
from app.ingestion.contracts import ConversationInput
from app.ingestion.service import IngestionSummary, ingest_conversations

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


class SimulatedConversationRequest(BaseModel):
    external_id: str
    scenario: str | None = None
    status: str | None = None
    occurred_at: datetime
    body: dict[str, Any]

    def to_input(self) -> ConversationInput:
        return ConversationInput.from_mapping(self.model_dump())


class SimulatedIngestionRequest(BaseModel):
    source_id: str
    items: list[SimulatedConversationRequest]


class IngestionSummaryResponse(BaseModel):
    inserted: int
    skipped: int


@router.post("/simulated", response_model=IngestionSummaryResponse)
def ingest_simulated(
    request: SimulatedIngestionRequest,
    session: Session = Depends(get_session),  # noqa: B008
) -> IngestionSummary:
    return ingest_conversations(
        session, request.source_id, [item.to_input() for item in request.items]
    )
