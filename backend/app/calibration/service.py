from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.calibration.models import CalibrationBatch, CalibrationReview
from app.evaluation.models import EvaluationResult, EvaluationRun
from app.shared.enums import CalibrationSelectionReason, Confidence, RunStatus
from app.shared.types import new_uuid

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SCORE_BOUNDARY = Decimal(5)
_PRIORITY_QUOTAS = (
    (CalibrationSelectionReason.LOW_CONFIDENCE, 8),
    (CalibrationSelectionReason.SCORE_BOUNDARY, 6),
    (CalibrationSelectionReason.SEVERE_ERROR, 4),
    (CalibrationSelectionReason.RANDOM_SAMPLE, 2),
)


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


def _candidates(
    session: Session, business_date: date
) -> list[tuple[EvaluationResult, CalibrationSelectionReason]]:
    window_start = datetime.combine(business_date - timedelta(days=6), datetime.min.time(), UTC)
    window_end = datetime.combine(business_date + timedelta(days=1), datetime.min.time(), UTC)
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

    selected: list[tuple[EvaluationResult, CalibrationSelectionReason]] = []
    for reason, quota in _PRIORITY_QUOTAS:
        selected.extend(buckets[reason][:quota])
        if len(selected) >= target_count:
            return selected[:target_count]

    selected_ids = {result.id for result, _ in selected}
    remaining = [candidate for candidate in candidates if candidate[0].id not in selected_ids]
    random.Random(business_date.toordinal()).shuffle(remaining)
    return selected + remaining[: target_count - len(selected)]
