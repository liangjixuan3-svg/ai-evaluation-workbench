from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_session
from app.retest.service import (
    InvalidRetestState,
    build_retest_sample,
    close_false_positive,
    complete_retest,
    mark_published,
)

router = APIRouter(tags=["retest"])


class ActorBody(BaseModel):
    actor: str = Field(min_length=1)


class FalsePositiveBody(ActorBody):
    reason: str = Field(min_length=1)


@router.post("/api/qa-versions/{qa_version_id}/publish")
def publish_qa(
    qa_version_id: str,
    body: ActorBody,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str]:
    try:
        run = mark_published(session, qa_version_id, body.actor)
        samples = build_retest_sample(session, run.id)
    except (LookupError, InvalidRetestState) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"retest_run_id": run.id, "status": run.status.value, "sample_count": str(len(samples))}


@router.post("/api/retests/{run_id}/complete")
def finish_retest(
    run_id: str,
    body: ActorBody,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str | float | None]:
    try:
        run = complete_retest(session, run_id, body.actor)
    except (LookupError, InvalidRetestState) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "id": run.id,
        "status": run.status.value,
        "replay_pass_rate": float(run.replay_pass_rate) if run.replay_pass_rate else None,
        "new_sample_pass_rate": (
            float(run.new_sample_pass_rate) if run.new_sample_pass_rate else None
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
