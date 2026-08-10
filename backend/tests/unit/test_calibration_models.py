from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.calibration.models import CalibrationBatch, CalibrationReview
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
    CalibrationBatchStatus,
    CalibrationDimension,
    CalibrationReviewStatus,
    CalibrationSelectionReason,
    Confidence,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


@pytest.fixture
def result(session: Session) -> EvaluationResult:
    suffix = uuid4().hex
    source = DataSource(name=f"source-{suffix}", kind="simulated")
    conversation = Conversation(data_source=source, external_id=f"conversation-{suffix}", body={})
    template = EvaluationTemplate(
        name=f"template-{suffix}",
        version="1",
        weights={"correctness": 1},
        threshold=Decimal("80.00"),
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
    )
    result = EvaluationResult(
        run=run,
        conversation=conversation,
        total_score=Decimal("90.00"),
        dimension_scores={"correctness": 90},
        passed=True,
        reason="Correct response",
        evidence=["answer"],
        confidence=Confidence.HIGH,
    )
    session.add(result)
    session.commit()
    return result


def test_calibration_models_keep_original_result_reference(
    session: Session, result: EvaluationResult
) -> None:
    batch = CalibrationBatch(batch_date=date(2026, 8, 10), target_count=20)
    session.add(batch)
    session.flush()
    review = CalibrationReview(
        batch_id=batch.id,
        evaluation_result_id=result.id,
        selection_reason=CalibrationSelectionReason.LOW_CONFIDENCE,
    )
    session.add(review)
    session.flush()

    assert batch.status == CalibrationBatchStatus.OPEN
    assert review.status == CalibrationReviewStatus.PENDING
    assert review.include_in_regression is False
    assert review.evaluation_result_id == result.id


def test_calibration_dimensions_match_the_five_dimension_contract() -> None:
    assert [dimension.value for dimension in CalibrationDimension] == [
        "correctness",
        "completeness",
        "relevance",
        "service_experience",
        "compliance",
        "other",
    ]


def test_sqlite_model_accepts_one_thousand_chinese_characters(
    session: Session, result: EvaluationResult
) -> None:
    batch = CalibrationBatch(batch_date=date(2026, 8, 10), target_count=20)
    session.add(batch)
    session.flush()
    review = CalibrationReview(
        batch_id=batch.id,
        evaluation_result_id=result.id,
        selection_reason=CalibrationSelectionReason.LOW_CONFIDENCE,
        status=CalibrationReviewStatus.CORRECTED,
        agreed=False,
        corrected_passed=True,
        disagreement_dimension=CalibrationDimension.CORRECTNESS,
        review_basis="中" * 1000,
        reviewed_by="审核人",
        reviewed_at=datetime(2026, 8, 10, tzinfo=UTC),
        include_in_regression=True,
    )
    session.add(review)

    session.flush()

    assert len(review.review_basis or "") == 1000


def test_calibration_batch_date_is_unique(session: Session) -> None:
    session.add(CalibrationBatch(batch_date=date(2026, 8, 10), target_count=20))
    session.commit()
    session.add(CalibrationBatch(batch_date=date(2026, 8, 10), target_count=20))

    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize("target_count", (0, 21))
def test_calibration_batch_rejects_target_count_outside_one_to_twenty(
    session: Session, target_count: int
) -> None:
    session.add(CalibrationBatch(batch_date=date(2026, 8, 10), target_count=target_count))

    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize(
    ("status", "changes"),
    (
        (CalibrationReviewStatus.PENDING, {"agreed": True}),
        (CalibrationReviewStatus.AGREED, {"agreed": True}),
        (CalibrationReviewStatus.CORRECTED, {"agreed": False}),
    ),
)
def test_calibration_review_rejects_invalid_status_combinations(
    session: Session,
    result: EvaluationResult,
    status: CalibrationReviewStatus,
    changes: dict[str, object],
) -> None:
    batch = CalibrationBatch(batch_date=date(2026, 8, 10), target_count=20)
    session.add(batch)
    session.flush()
    review = CalibrationReview(
        batch_id=batch.id,
        evaluation_result_id=result.id,
        selection_reason=CalibrationSelectionReason.LOW_CONFIDENCE,
        status=status,
        **changes,
    )
    session.add(review)

    with pytest.raises(IntegrityError):
        session.flush()


def test_calibration_review_rejects_review_basis_longer_than_one_thousand_characters(
    session: Session, result: EvaluationResult
) -> None:
    batch = CalibrationBatch(batch_date=date(2026, 8, 10), target_count=20)
    session.add(batch)
    session.flush()
    session.add(
        CalibrationReview(
            batch_id=batch.id,
            evaluation_result_id=result.id,
            selection_reason=CalibrationSelectionReason.LOW_CONFIDENCE,
            status=CalibrationReviewStatus.CORRECTED,
            agreed=False,
            corrected_passed=True,
            disagreement_dimension=CalibrationDimension.CORRECTNESS,
            review_basis="x" * 1001,
            reviewed_by="reviewer@example.com",
            reviewed_at=datetime(2026, 8, 10, tzinfo=UTC),
            include_in_regression=True,
        )
    )

    with pytest.raises(IntegrityError):
        session.flush()


def test_calibration_review_can_reference_an_evaluation_result_once(
    session: Session, result: EvaluationResult
) -> None:
    first_batch = CalibrationBatch(batch_date=date(2026, 8, 10), target_count=20)
    second_batch = CalibrationBatch(batch_date=date(2026, 8, 11), target_count=20)
    session.add_all((first_batch, second_batch))
    session.flush()
    session.add(
        CalibrationReview(
            batch_id=first_batch.id,
            evaluation_result_id=result.id,
            selection_reason=CalibrationSelectionReason.LOW_CONFIDENCE,
        )
    )
    session.commit()
    session.add(
        CalibrationReview(
            batch_id=second_batch.id,
            evaluation_result_id=result.id,
            selection_reason=CalibrationSelectionReason.LOW_CONFIDENCE,
        )
    )

    with pytest.raises(IntegrityError):
        session.flush()
