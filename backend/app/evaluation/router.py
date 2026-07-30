from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.evaluation.models import (
    EvaluationRun,
    EvaluationTemplate,
    PromptVersion,
    RuleVersion,
)
from app.evaluation.openai_compatible import build_evaluation_provider, provider_is_configured
from app.evaluation.providers import EvaluationProvider
from app.ingestion.models import SamplingBatch
from app.jobs.repository import enqueue_job
from app.shared.audit import record_audit

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


def get_evaluation_provider() -> EvaluationProvider:
    return build_evaluation_provider(settings)


@router.get("/provider-status")
def get_provider_status() -> dict[str, str | bool | None]:
    return {
        "configured": provider_is_configured(settings),
        "base_url": settings.llm_base_url or None,
        "model": settings.llm_model or None,
    }


class CreateEvaluationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sampling_batch_id: str
    template_id: str
    prompt_version_id: str
    rule_version_id: str
    model_parameters: dict[str, Any] = Field(default_factory=dict)


class EvaluationRunResponse(BaseModel):
    id: str
    status: str


@router.post(
    "/runs",
    response_model=EvaluationRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_evaluation_run(
    request: CreateEvaluationRunRequest,
    session: Annotated[Session, Depends(get_session)],
    provider: Annotated[EvaluationProvider, Depends(get_evaluation_provider)],
) -> EvaluationRunResponse:
    required_records = (
        (SamplingBatch, request.sampling_batch_id, "sampling batch"),
        (EvaluationTemplate, request.template_id, "evaluation template"),
        (PromptVersion, request.prompt_version_id, "prompt version"),
        (RuleVersion, request.rule_version_id, "rule version"),
    )
    for model_type, record_id, label in required_records:
        if session.get(model_type, record_id) is None:
            session.rollback()
            raise HTTPException(status_code=404, detail=f"{label} not found")

    identity = provider.identity
    run = EvaluationRun(
        sampling_batch_id=request.sampling_batch_id,
        template_id=request.template_id,
        prompt_version_id=request.prompt_version_id,
        rule_version_id=request.rule_version_id,
        provider=identity.provider,
        model=identity.model,
        model_parameters=request.model_parameters,
    )
    session.add(run)
    session.flush()
    record_audit(
        session,
        actor="api",
        action="evaluation_run_created",
        entity_type="evaluation_run",
        entity_id=run.id,
        payload={
            "provider": identity.provider,
            "model": identity.model,
            "template_id": request.template_id,
            "prompt_version_id": request.prompt_version_id,
            "rule_version_id": request.rule_version_id,
        },
    )
    enqueue_job(
        session,
        "evaluation_batch",
        {"run_id": run.id},
        f"evaluation-batch:{run.id}",
    )
    return EvaluationRunResponse(id=run.id, status=run.status.value)
