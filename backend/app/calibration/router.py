from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.calibration.contracts import AgreeReviewInput, DisagreeReviewInput
from app.calibration.service import (
    agree_with_evaluation,
    calibration_review_detail,
    calibration_workspace,
    disagree_with_evaluation,
    ensure_today_batch,
    review_payload,
)
from app.db import get_session

router = APIRouter(prefix="/api/calibration", tags=["calibration"])


@router.post("/batches/today/ensure")
def ensure_today_calibration_batch(
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    try:
        batch = ensure_today_batch(session)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "id": batch.id,
        "batch_date": batch.batch_date.isoformat(),
        "target_count": batch.target_count,
        "status": batch.status.value,
    }


@router.get("/workspace")
def get_calibration_workspace(
    session: Annotated[Session, Depends(get_session)],
    status: Literal["pending", "reviewed", "all"] = Query(default="pending"),
) -> dict:
    return calibration_workspace(session, status)


@router.get("/reviews/{review_id}")
def get_calibration_review(
    review_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict:
    try:
        return calibration_review_detail(session, review_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/reviews/{review_id}/agree")
def agree_review(
    review_id: str,
    input: AgreeReviewInput,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    try:
        return review_payload(agree_with_evaluation(session, review_id, input.actor))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/reviews/{review_id}/disagree")
def disagree_review(
    review_id: str,
    input: DisagreeReviewInput,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    try:
        return review_payload(disagree_with_evaluation(session, review_id, input))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
