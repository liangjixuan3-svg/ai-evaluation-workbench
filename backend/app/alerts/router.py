from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import Alert, AlertResult
from app.analysis.models import ClusterMember, RootCauseSuggestion
from app.analysis.service import attribute_cluster
from app.db import get_session
from app.evaluation.providers import EvaluationProvider, FakeEvaluationProvider

router = APIRouter(tags=["alerts"])


def get_evaluation_provider() -> EvaluationProvider:
    return FakeEvaluationProvider()


class AlertCard(BaseModel):
    id: str
    kind: str
    priority: str
    scenario: str | None
    root_cause: str | None
    status: str
    impact_count: int


class AttributionSuggestionResponse(BaseModel):
    root_cause: str
    reason: str
    evidence: list[str]
    confidence: str


class AlertDetailResponse(AlertCard):
    result_ids: list[str]
    root_cause_suggestion: AttributionSuggestionResponse | None


@router.get("/api/alerts/{alert_id}", response_model=AlertDetailResponse)
def get_alert_detail(
    alert_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> AlertDetailResponse:
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    result_ids = list(
        session.scalars(
            select(AlertResult.evaluation_result_id)
            .where(AlertResult.alert_id == alert.id)
            .order_by(AlertResult.evaluation_result_id)
        )
    )
    suggestion = session.scalar(
        select(RootCauseSuggestion)
        .join(ClusterMember, ClusterMember.cluster_id == RootCauseSuggestion.cluster_id)
        .where(ClusterMember.evaluation_result_id.in_(result_ids))
        .order_by(RootCauseSuggestion.created_at.desc())
    )
    return AlertDetailResponse(
        **_alert_card(alert).model_dump(),
        result_ids=result_ids,
        root_cause_suggestion=(
            AttributionSuggestionResponse(
                root_cause=suggestion.root_cause.value,
                reason=suggestion.reason,
                evidence=suggestion.evidence,
                confidence=suggestion.confidence.value,
            )
            if suggestion
            else None
        ),
    )


@router.post("/api/badcases/{cluster_id}/attribution", response_model=AttributionSuggestionResponse)
def create_attribution_suggestion(
    cluster_id: str,
    session: Annotated[Session, Depends(get_session)],
    provider: Annotated[EvaluationProvider, Depends(get_evaluation_provider)],
) -> AttributionSuggestionResponse:
    try:
        suggestion = attribute_cluster(session, cluster_id, provider)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return AttributionSuggestionResponse(
        root_cause=suggestion.root_cause.value,
        reason=suggestion.reason,
        evidence=suggestion.evidence,
        confidence=suggestion.confidence.value,
    )


def _alert_card(alert: Alert) -> AlertCard:
    return AlertCard(
        id=alert.id,
        kind=alert.kind,
        priority=alert.priority,
        scenario=alert.scenario,
        root_cause=alert.root_cause.value if alert.root_cause else None,
        status=alert.status.value,
        impact_count=alert.impact_count,
    )
