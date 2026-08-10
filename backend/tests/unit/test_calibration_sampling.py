from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.calibration.models import CalibrationBatch, CalibrationReview
from app.calibration.service import ensure_today_batch, selection_reason
from app.db import Base
from app.evaluation.models import (
    EvaluationResult,
    EvaluationRun,
    EvaluationTemplate,
    PromptVersion,
    RuleVersion,
)
from app.ingestion.models import Conversation, DataSource
from app.quality_standards.models import QualityStandardVersion  # noqa: F401
from app.shared.enums import (
    CalibrationSelectionReason,
    Confidence,
    RunStatus,
)

TODAY = date(2026, 8, 10)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{tmp_path / 'calibration.db'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Session:
    with Session(engine, expire_on_commit=False) as session:
        yield session


def _at(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, tzinfo=UTC)


def _add_result(
    session: Session,
    *,
    created_on: date = TODAY - timedelta(days=1),
    confidence: Confidence = Confidence.HIGH,
    score: str = "90.00",
    threshold: str = "80.00",
    status: RunStatus = RunStatus.SUCCEEDED,
    severe_factual_error: bool = False,
    severe_compliance_error: bool = False,
) -> EvaluationResult:
    suffix = uuid4().hex
    created_at = _at(created_on)
    source = DataSource(name=f"source-{suffix}", kind="simulated")
    conversation = Conversation(data_source=source, external_id=f"conversation-{suffix}", body={})
    template = EvaluationTemplate(
        name=f"template-{suffix}",
        version="1",
        weights={"correctness": 1},
        threshold=Decimal(threshold),
        veto_rules={},
    )
    prompt = PromptVersion(name=f"prompt-{suffix}", version="1", content="Evaluate")
    rule = RuleVersion(kind=f"evaluation-{suffix}", version="1", config={})
    run = EvaluationRun(
        template=template,
        prompt_version=prompt,
        rule_version=rule,
        provider="fake",
        model="fake-v1",
        model_parameters={},
        status=status,
        completed_at=created_at if status is RunStatus.SUCCEEDED else None,
        created_at=created_at,
    )
    result = EvaluationResult(
        run=run,
        conversation=conversation,
        total_score=Decimal(score),
        dimension_scores={"correctness": 90},
        passed=True,
        reason="Correct response",
        evidence=["answer"],
        confidence=confidence,
        severe_factual_error=severe_factual_error,
        severe_compliance_error=severe_compliance_error,
        created_at=created_at,
    )
    session.add(result)
    return result


def _reviews(session: Session, batch: CalibrationBatch) -> list[CalibrationReview]:
    return list(
        session.scalars(
            select(CalibrationReview)
            .where(CalibrationReview.batch_id == batch.id)
            .order_by(CalibrationReview.evaluation_result_id)
        )
    )


def test_calibration_selection_reasons_include_severe_error() -> None:
    assert CalibrationSelectionReason.SEVERE_ERROR.value == "severe_error"


def test_selection_reason_applies_priority_order(session: Session) -> None:
    low = _add_result(
        session,
        confidence=Confidence.LOW,
        score="80.00",
        severe_factual_error=True,
    )
    borderline = _add_result(session, score="75.00", severe_factual_error=True)
    severe = _add_result(session, score="60.00", severe_compliance_error=True)
    ordinary = _add_result(session)
    session.commit()

    assert selection_reason(low, Decimal("80.00")) is CalibrationSelectionReason.LOW_CONFIDENCE
    assert selection_reason(borderline, Decimal("80.00")) is CalibrationSelectionReason.SCORE_BOUNDARY
    assert selection_reason(severe, Decimal("80.00")) is CalibrationSelectionReason.SEVERE_ERROR
    assert selection_reason(ordinary, Decimal("80.00")) is None


def test_ensure_today_batch_uses_stratified_priority_quotas(session: Session) -> None:
    for _ in range(10):
        _add_result(
            session,
            confidence=Confidence.LOW,
            score="80.00",
            severe_factual_error=True,
        )
    for _ in range(8):
        _add_result(session, score="75.00", severe_factual_error=True)
    for _ in range(6):
        _add_result(session, score="60.00", severe_compliance_error=True)
    for _ in range(10):
        _add_result(session, score="95.00")
    session.commit()

    batch = ensure_today_batch(session, batch_date=TODAY)
    reasons = Counter(review.selection_reason for review in _reviews(session, batch))

    assert len(_reviews(session, batch)) == 20
    assert reasons[CalibrationSelectionReason.LOW_CONFIDENCE] == 8
    assert reasons[CalibrationSelectionReason.SCORE_BOUNDARY] == 6
    assert reasons[CalibrationSelectionReason.SEVERE_ERROR] == 4
    assert reasons[CalibrationSelectionReason.RANDOM_SAMPLE] == 2


def test_ensure_today_batch_is_idempotent_for_the_business_date(session: Session) -> None:
    for _ in range(3):
        _add_result(session)
    session.commit()

    first = ensure_today_batch(session, batch_date=TODAY)
    first_review_ids = [review.id for review in _reviews(session, first)]
    second = ensure_today_batch(session, batch_date=TODAY)

    assert second.id == first.id
    assert [review.id for review in _reviews(session, second)] == first_review_ids


def test_ensure_today_batch_fills_missing_categories_from_remaining_candidates(
    session: Session,
) -> None:
    for _ in range(2):
        _add_result(session, confidence=Confidence.LOW)
    for _ in range(20):
        _add_result(session)
    session.commit()

    batch = ensure_today_batch(session, batch_date=TODAY)
    reasons = Counter(review.selection_reason for review in _reviews(session, batch))

    assert len(_reviews(session, batch)) == 20
    assert reasons[CalibrationSelectionReason.LOW_CONFIDENCE] == 2
    assert reasons[CalibrationSelectionReason.RANDOM_SAMPLE] == 18


def test_ensure_today_batch_creates_only_available_candidates(session: Session) -> None:
    _add_result(session, confidence=Confidence.LOW)
    _add_result(session, score="75.00")
    _add_result(session, severe_factual_error=True, score="60.00")
    session.commit()

    batch = ensure_today_batch(session, batch_date=TODAY)

    assert len(_reviews(session, batch)) == 3


def test_ensure_today_batch_excludes_old_incomplete_and_historical_results(session: Session) -> None:
    eligible = _add_result(session)
    _add_result(session, created_on=TODAY - timedelta(days=7))
    _add_result(session, status=RunStatus.RUNNING)
    historical = _add_result(session)
    session.commit()
    previous_batch = CalibrationBatch(batch_date=TODAY - timedelta(days=1), target_count=20)
    session.add(previous_batch)
    session.flush()
    session.add(
        CalibrationReview(
            batch_id=previous_batch.id,
            evaluation_result_id=historical.id,
            selection_reason=CalibrationSelectionReason.RANDOM_SAMPLE,
        )
    )
    session.commit()

    batch = ensure_today_batch(session, batch_date=TODAY)

    assert [review.evaluation_result_id for review in _reviews(session, batch)] == [eligible.id]


def test_ensure_today_batch_uses_each_results_template_threshold(session: Session) -> None:
    near_its_threshold = _add_result(session, score="85.00", threshold="90.00")
    outside_its_threshold = _add_result(session, score="85.00", threshold="79.00")
    session.commit()

    batch = ensure_today_batch(session, batch_date=TODAY)
    reviews_by_result = {review.evaluation_result_id: review for review in _reviews(session, batch)}

    assert (
        reviews_by_result[near_its_threshold.id].selection_reason
        is CalibrationSelectionReason.SCORE_BOUNDARY
    )
    assert (
        reviews_by_result[outside_its_threshold.id].selection_reason
        is CalibrationSelectionReason.RANDOM_SAMPLE
    )


def test_ensure_today_batch_rolls_back_and_returns_batch_created_concurrently(
    session: Session,
    engine: Engine,
) -> None:
    _add_result(session)
    session.commit()
    competing_batch = CalibrationBatch(batch_date=TODAY, target_count=20)

    def create_competing_batch(_: Session) -> None:
        with Session(engine, expire_on_commit=False) as competing_session:
            competing_session.add(competing_batch)
            competing_session.commit()

    event.listen(session, "before_commit", create_competing_batch, once=True)

    batch = ensure_today_batch(session, batch_date=TODAY)

    assert batch.id == competing_batch.id
    assert session.get(CalibrationBatch, competing_batch.id) is not None
