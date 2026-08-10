from __future__ import annotations

import random
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.calibration.contracts import DisagreeReviewInput
from app.calibration.models import CalibrationBatch, CalibrationReview
from app.evaluation.models import EvaluationResult, EvaluationRun
from app.ingestion.models import Conversation
from app.ingestion.redaction import redact_text
from app.shared.enums import (
    CalibrationBatchStatus,
    CalibrationReviewStatus,
    CalibrationSelectionReason,
    Confidence,
    RunStatus,
)
from app.shared.types import new_uuid, utc_now

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SCORE_BOUNDARY = Decimal(5)
_PRIORITY_QUOTAS = (
    (CalibrationSelectionReason.LOW_CONFIDENCE, 8),
    (CalibrationSelectionReason.SCORE_BOUNDARY, 6),
    (CalibrationSelectionReason.SEVERE_ERROR, 4),
    (CalibrationSelectionReason.RANDOM_SAMPLE, 2),
)
_SAFE_MODEL_PARAMETER_KEYS = {
    "frequency_penalty",
    "max_tokens",
    "presence_penalty",
    "seed",
    "stop",
    "temperature",
    "top_p",
}

CalibrationWorkspaceStatus = Literal["pending", "reviewed", "all"]


def selection_reason(
    result: EvaluationResult, threshold: Decimal
) -> CalibrationSelectionReason | None:
    """Classify a result once, using the documented priority order."""
    if result.confidence is Confidence.LOW:
        return CalibrationSelectionReason.LOW_CONFIDENCE
    if abs(result.total_score - threshold) <= _SCORE_BOUNDARY:
        return CalibrationSelectionReason.SCORE_BOUNDARY
    if result.severe_factual_error or result.severe_compliance_error:
        return CalibrationSelectionReason.SEVERE_ERROR
    return None


def ensure_today_batch(
    session: Session, batch_date: date | None = None, target_count: int = 20
) -> CalibrationBatch:
    """Return the idempotent calibration batch for a Shanghai business date."""
    if not 1 <= target_count <= 20:
        raise ValueError("target_count must be between 1 and 20")

    business_date = batch_date or datetime.now(_SHANGHAI).date()
    existing = session.scalar(
        select(CalibrationBatch).where(CalibrationBatch.batch_date == business_date)
    )
    if existing is not None:
        return existing

    candidates = _candidates(session, business_date)
    selected = _select_candidates(candidates, business_date, target_count)
    batch = CalibrationBatch(
        id=new_uuid(),
        batch_date=business_date,
        target_count=target_count,
        status=(
            CalibrationBatchStatus.OPEN if selected else CalibrationBatchStatus.COMPLETED
        ),
        completed_at=utc_now() if not selected else None,
    )
    session.add(batch)
    session.add_all(
        CalibrationReview(
            batch_id=batch.id,
            evaluation_result_id=result.id,
            selection_reason=reason,
        )
        for result, reason in selected
    )

    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(CalibrationBatch).where(CalibrationBatch.batch_date == business_date)
        )
        if existing is not None:
            return existing
        raise
    return batch


def calibration_workspace(
    session: Session, status: CalibrationWorkspaceStatus = "pending"
) -> dict[str, Any]:
    """Return today's calibration queue without initiating model evaluation."""
    batch = session.scalar(
        select(CalibrationBatch).where(CalibrationBatch.batch_date == datetime.now(_SHANGHAI).date())
    )
    if batch is None:
        return {
            "batch": None,
            "summary": {
                "reviewed": 0,
                "total": 0,
                "pending": 0,
                "agreement_rate": None,
                "top_disagreement_dimension": None,
            },
            "items": [],
        }

    reviews = list(
        session.scalars(
            select(CalibrationReview)
            .options(
                joinedload(CalibrationReview.evaluation_result)
                .joinedload(EvaluationResult.conversation)
                .joinedload(Conversation.data_source)
            )
            .where(CalibrationReview.batch_id == batch.id)
            .order_by(CalibrationReview.created_at, CalibrationReview.id)
        )
    )
    reviews.sort(key=_workspace_sort_key)
    reviewed = [review for review in reviews if review.status is not CalibrationReviewStatus.PENDING]
    disagreements = [
        review.disagreement_dimension.value
        for review in reviewed
        if review.disagreement_dimension is not None
    ]
    if status == "pending":
        displayed = [review for review in reviews if review.status is CalibrationReviewStatus.PENDING]
    elif status == "reviewed":
        displayed = reviewed
    else:
        displayed = reviews
    return _redact_json({
        "batch": {
            "id": batch.id,
            "batch_date": batch.batch_date.isoformat(),
            "target_count": batch.target_count,
            "status": batch.status.value,
        },
        "summary": {
            "reviewed": len(reviewed),
            "total": len(reviews),
            "pending": len(reviews) - len(reviewed),
            "agreement_rate": (
                sum(review.agreed is True for review in reviewed) / len(reviewed)
                if reviewed
                else None
            ),
            "top_disagreement_dimension": _top_disagreement_dimension(disagreements),
        },
        "items": [_workspace_item(review) for review in displayed],
    })


def calibration_review_detail(session: Session, review_id: str) -> dict[str, Any]:
    review = session.scalar(
        select(CalibrationReview)
        .options(
            joinedload(CalibrationReview.evaluation_result)
            .joinedload(EvaluationResult.conversation)
            .joinedload(Conversation.data_source),
            joinedload(CalibrationReview.evaluation_result)
            .joinedload(EvaluationResult.run)
            .joinedload(EvaluationRun.prompt_version),
            joinedload(CalibrationReview.evaluation_result)
            .joinedload(EvaluationResult.run)
            .joinedload(EvaluationRun.quality_standard_version),
        )
        .where(CalibrationReview.id == review_id)
    )
    if review is None:
        raise LookupError("calibration review does not exist")
    result = review.evaluation_result
    run = result.run
    conversation = result.conversation
    quality_standard = run.quality_standard_version
    return _redact_json({
        **review_payload(review),
        "batch": _batch_payload(session.get(CalibrationBatch, review.batch_id)),
        "data_source": _data_source_payload(conversation),
        "conversation": {
            "id": conversation.id,
            "external_id": conversation.external_id,
            "scenario": conversation.scenario,
            "status": conversation.status,
            "messages": _redact_json(conversation.body.get("messages", [])),
        },
        "evaluation": {
            "total_score": float(result.total_score),
            "dimension_scores": result.dimension_scores,
            "passed": result.passed,
            "confidence": result.confidence.value,
            "reason": result.reason,
            "evidence": result.evidence,
            "severe_factual_error": result.severe_factual_error,
            "severe_compliance_error": result.severe_compliance_error,
        },
        "locked_rule": {
            "quality_standard": (
                {
                    "id": quality_standard.id,
                    "version_number": quality_standard.version_number,
                    "rules": quality_standard.rules,
                }
                if quality_standard is not None
                else None
            ),
            "prompt": {
                "id": run.prompt_version.id,
                "name": run.prompt_version.name,
                "version": run.prompt_version.version,
                "content": run.prompt_version.content,
            },
            "model": {
                "provider": run.provider,
                "model": run.model,
                "parameters": _sanitize_model_parameters(run.model_parameters),
            },
        },
    })


def agree_with_evaluation(session: Session, review_id: str, actor: str) -> CalibrationReview:
    batch, review = _batch_and_review_for_update(session, review_id)
    if review.status is not CalibrationReviewStatus.PENDING:
        return review
    actor = actor.strip()
    if not actor:
        raise ValueError("actor is required")
    review.status = CalibrationReviewStatus.AGREED
    review.agreed = True
    review.reviewed_by = actor
    review.reviewed_at = utc_now()
    session.flush()
    _complete_batch_when_fully_reviewed(session, batch)
    session.commit()
    return review


def disagree_with_evaluation(
    session: Session, review_id: str, input: DisagreeReviewInput
) -> CalibrationReview:
    batch, review = _batch_and_review_for_update(session, review_id)
    if review.status is not CalibrationReviewStatus.PENDING:
        return review
    actor = input.actor.strip()
    review_basis = input.review_basis.strip()
    if not actor:
        raise ValueError("actor is required")
    if not review_basis:
        raise ValueError("review_basis is required")
    if len(review_basis) > 1000:
        raise ValueError("review_basis must be at most 1000 characters")
    review.status = CalibrationReviewStatus.CORRECTED
    review.agreed = False
    review.corrected_passed = input.corrected_passed
    review.disagreement_dimension = input.disagreement_dimension
    review.review_basis = review_basis
    review.reviewed_by = actor
    review.reviewed_at = utc_now()
    review.include_in_regression = True
    session.flush()
    _complete_batch_when_fully_reviewed(session, batch)
    session.commit()
    return review


def review_payload(review: CalibrationReview) -> dict[str, Any]:
    return _redact_json({
        "id": review.id,
        "review_id": review.id,
        "evaluation_result_id": review.evaluation_result_id,
        "selection_reason": review.selection_reason.value,
        "status": review.status.value,
        "agreed": review.agreed,
        "corrected_passed": review.corrected_passed,
        "disagreement_dimension": (
            review.disagreement_dimension.value if review.disagreement_dimension is not None else None
        ),
        "review_basis": review.review_basis,
        "reviewed_by": review.reviewed_by,
        "reviewed_at": review.reviewed_at.isoformat() if review.reviewed_at else None,
        "include_in_regression": review.include_in_regression,
    })


def _batch_and_review_for_update(
    session: Session, review_id: str
) -> tuple[CalibrationBatch, CalibrationReview]:
    batch_id = session.scalar(
        select(CalibrationReview.batch_id).where(CalibrationReview.id == review_id)
    )
    if batch_id is None:
        raise LookupError("calibration review does not exist")
    batch = _batch_for_update(session, batch_id)
    review = _review_for_update(session, review_id)
    return batch, review


def _batch_lock_statement(batch_id: str):
    return select(CalibrationBatch).where(CalibrationBatch.id == batch_id).with_for_update()


def _batch_for_update(session: Session, batch_id: str) -> CalibrationBatch:
    batch = session.scalar(_batch_lock_statement(batch_id))
    if batch is None:
        raise LookupError("calibration batch does not exist")
    return batch


def _review_for_update(session: Session, review_id: str) -> CalibrationReview:
    review = session.scalar(
        select(CalibrationReview)
        .where(CalibrationReview.id == review_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if review is None:
        raise LookupError("calibration review does not exist")
    return review


def _complete_batch_when_fully_reviewed(session: Session, batch: CalibrationBatch) -> None:
    pending_review = session.scalar(
        select(CalibrationReview.id)
        .where(
            CalibrationReview.batch_id == batch.id,
            CalibrationReview.status == CalibrationReviewStatus.PENDING,
        )
        .limit(1)
        .with_for_update()
    )
    if pending_review is None:
        batch.status = CalibrationBatchStatus.COMPLETED
        batch.completed_at = utc_now()


def _workspace_item(review: CalibrationReview) -> dict[str, Any]:
    result = review.evaluation_result
    return {
        **review_payload(review),
        "data_source": _data_source_payload(result.conversation),
        "scenario": result.conversation.scenario,
        "total_score": float(result.total_score),
        "passed": result.passed,
        "confidence": result.confidence.value,
    }


def _data_source_payload(conversation: Conversation) -> dict[str, str]:
    return {
        "name": conversation.data_source.name,
        "kind": conversation.data_source.kind,
    }


def _workspace_sort_key(review: CalibrationReview) -> tuple[int, str]:
    priority = {
        CalibrationSelectionReason.LOW_CONFIDENCE: 0,
        CalibrationSelectionReason.SCORE_BOUNDARY: 1,
        CalibrationSelectionReason.SEVERE_ERROR: 2,
        CalibrationSelectionReason.RANDOM_SAMPLE: 3,
    }
    return priority[review.selection_reason], review.id


def _top_disagreement_dimension(dimensions: list[str]) -> str | None:
    if not dimensions:
        return None
    counts = Counter(dimensions)
    return min(counts, key=lambda dimension: (-counts[dimension], dimension))


def _batch_payload(batch: CalibrationBatch | None) -> dict[str, Any] | None:
    if batch is None:
        return None
    return {
        "id": batch.id,
        "batch_date": batch.batch_date.isoformat(),
        "target_count": batch.target_count,
        "status": batch.status.value,
    }


def _redact_json(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [_redact_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_json(item) for key, item in value.items()}
    return value


def _sanitize_model_parameters(value: Any) -> Any:
    if not isinstance(value, dict):
        return {}
    return {
        key: _redact_json(item)
        for key, item in value.items()
        if str(key).casefold() in _SAFE_MODEL_PARAMETER_KEYS
    }


def _candidates(
    session: Session, business_date: date
) -> list[tuple[EvaluationResult, CalibrationSelectionReason]]:
    window_start = _shanghai_day_start(business_date - timedelta(days=6))
    window_end = _shanghai_day_start(business_date + timedelta(days=1))
    stmt = (
        select(EvaluationResult)
        .join(EvaluationResult.run)
        .options(joinedload(EvaluationResult.run).joinedload(EvaluationRun.template))
        .where(EvaluationResult.created_at >= window_start)
        .where(EvaluationResult.created_at < window_end)
        .where(EvaluationRun.status == RunStatus.SUCCEEDED)
        .where(EvaluationRun.completed_at.is_not(None))
        .where(
            ~exists(
                select(CalibrationReview.id).where(
                    CalibrationReview.evaluation_result_id == EvaluationResult.id
                )
            )
        )
    )
    rows = session.scalars(stmt).unique().all()
    return [
        (
            result,
            selection_reason(result, result.run.template.threshold)
            or CalibrationSelectionReason.RANDOM_SAMPLE,
        )
        for result in rows
    ]


def _shanghai_day_start(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), _SHANGHAI).astimezone(UTC)


def _select_candidates(
    candidates: list[tuple[EvaluationResult, CalibrationSelectionReason]],
    business_date: date,
    target_count: int,
) -> list[tuple[EvaluationResult, CalibrationSelectionReason]]:
    buckets = {reason: [] for reason, _ in _PRIORITY_QUOTAS}
    for candidate in candidates:
        buckets[candidate[1]].append(candidate)
    for bucket in buckets.values():
        bucket.sort(key=lambda item: item[0].id)
    random.Random(business_date.toordinal()).shuffle(
        buckets[CalibrationSelectionReason.RANDOM_SAMPLE]
    )

    selected: list[tuple[EvaluationResult, CalibrationSelectionReason]] = []
    for reason, quota in _PRIORITY_QUOTAS:
        selected.extend(buckets[reason][:quota])
        if len(selected) >= target_count:
            return selected[:target_count]

    selected_ids = {result.id for result, _ in selected}
    remaining = [candidate for candidate in candidates if candidate[0].id not in selected_ids]
    remaining.sort(key=lambda item: item[0].id)
    random.Random(business_date.toordinal()).shuffle(remaining)
    return selected + remaining[: target_count - len(selected)]
