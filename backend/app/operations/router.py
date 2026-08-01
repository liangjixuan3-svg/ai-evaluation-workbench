from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.evaluation.openai_compatible import build_evaluation_provider, provider_is_configured
from app.evaluation.providers import EvaluationProvider
from app.operations.service import (
    StartEvaluation,
    create_evaluation_operation,
    operation_detail,
    operation_results,
)

router = APIRouter(prefix="/api/operations", tags=["operations"])


def get_operation_provider() -> EvaluationProvider:
    if not provider_is_configured(settings):
        raise HTTPException(status_code=503, detail="真实模型尚未配置")
    return build_evaluation_provider(settings)


class StartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    import_id: str
    quality_standard_version_id: str | None = None
    prompt_version_id: str
    sample_size: int = Field(ge=1, le=10_000)
    strategy: Literal["random", "risk_first", "scenario_weighted"]
    threshold: float = Field(ge=0, le=100)
    seed: int
    actor: str = "operator"


@router.post("/evaluations", status_code=status.HTTP_201_CREATED)
def start_evaluation(
    body: StartBody,
    session: Annotated[Session, Depends(get_session)],
    provider: Annotated[EvaluationProvider, Depends(get_operation_provider)],
) -> dict[str, str]:
    try:
        run = create_evaluation_operation(
            session,
            StartEvaluation(**body.model_dump()),
            provider,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"run_id": run.id, "status": run.status.value}


@router.get("/evaluations/{run_id}")
def get_evaluation_operation(
    run_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict:
    try:
        return operation_detail(session, run_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/evaluations/{run_id}/results")
def get_evaluation_results(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    try:
        return operation_results(session, run_id, offset, limit)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
