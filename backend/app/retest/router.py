from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.evaluation.openai_compatible import build_evaluation_provider, provider_is_configured
from app.evaluation.providers import EvaluationProvider
from app.retest.service import (
    InvalidRetestState,
    RetestExecutionError,
    build_retest_sample,
    close_false_positive,
    execute_retest,
    mark_published,
    retest_workspace,
    retest_workspace_detail,
)
from app.shared.enums import RetestStatus

router = APIRouter(tags=["retest"])


class ActorBody(BaseModel):
    actor: str = Field(min_length=1)


class PublishBody(ActorBody):
    release_note: str = Field(default="", max_length=1000)


class FalsePositiveBody(ActorBody):
    reason: str = Field(min_length=1)


def get_retest_provider() -> EvaluationProvider:
    if not provider_is_configured(settings):
        raise HTTPException(status_code=503, detail="真实模型尚未配置")
    return build_evaluation_provider(settings)


@router.get("/api/retest-workspace")
def get_retest_workspace(
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    return retest_workspace(session)


@router.get("/api/retest-workspace/{run_id}")
def get_retest_workspace_detail(
    run_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict:
    try:
        return retest_workspace_detail(session, run_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/api/qa-versions/{qa_version_id}/publish")
def publish_qa(
    qa_version_id: str,
    body: PublishBody,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    try:
        run = mark_published(session, qa_version_id, body.actor, body.release_note)
        samples = build_retest_sample(session, run.id) if run.status == RetestStatus.QUEUED else []
    except (LookupError, InvalidRetestState) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    detail = retest_workspace_detail(session, run.id)
    sample_count = (
        len(samples)
        if samples
        else detail["replay_samples"]["available"] + detail["new_samples"]["available"]
    )
    return {
        "retest_run_id": run.id,
        "status": run.status.value,
        "sample_count": sample_count,
        "workspace_state": detail["workspace_state"],
    }


@router.post("/api/retests/{run_id}/refresh-samples")
def refresh_retest_samples(
    run_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict:
    try:
        build_retest_sample(session, run_id)
        return retest_workspace_detail(session, run_id)
    except (LookupError, InvalidRetestState) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/api/retests/{run_id}/execute")
def run_retest(
    run_id: str,
    body: ActorBody,
    session: Annotated[Session, Depends(get_session)],
    provider: Annotated[EvaluationProvider, Depends(get_retest_provider)],
) -> dict:
    try:
        run = execute_retest(session, run_id, body.actor, provider)
    except RetestExecutionError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except (LookupError, InvalidRetestState, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "id": run.id,
        "status": run.status.value,
        "replay_pass_rate": (
            float(run.replay_pass_rate) if run.replay_pass_rate is not None else None
        ),
        "new_sample_pass_rate": (
            float(run.new_sample_pass_rate) if run.new_sample_pass_rate is not None else None
        ),
    }


@router.post("/api/alerts/{alert_id}/false-positive")
def mark_false_positive(
    alert_id: str,
    body: FalsePositiveBody,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str]:
    try:
        alert = close_false_positive(session, alert_id, body.actor, body.reason)
    except (LookupError, InvalidRetestState) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"id": alert.id, "status": alert.status.value}
