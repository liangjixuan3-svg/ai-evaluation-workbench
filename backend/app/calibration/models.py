from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.shared.enums import (
    CalibrationBatchStatus,
    CalibrationDimension,
    CalibrationReviewStatus,
    CalibrationSelectionReason,
)
from app.shared.types import MYSQL_TABLE_ARGS, UTCDateTime, enum_type, utc_now, uuid_primary_key

if TYPE_CHECKING:
    from app.evaluation.models import EvaluationResult


class CalibrationBatch(Base):
    __tablename__ = "calibration_batches"
    __table_args__ = (
        UniqueConstraint("batch_date", name="uq_calibration_batch_date"),
        CheckConstraint("target_count BETWEEN 1 AND 20", name="ck_calibration_batch_target_count"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[str] = uuid_primary_key()
    batch_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[CalibrationBatchStatus] = mapped_column(
        enum_type(CalibrationBatchStatus), default=CalibrationBatchStatus.OPEN, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class CalibrationReview(Base):
    __tablename__ = "calibration_reviews"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_result_id", name="uq_calibration_review_evaluation_result"
        ),
        CheckConstraint(
            "(status = 'pending' AND agreed IS NULL AND corrected_passed IS NULL "
            "AND disagreement_dimension IS NULL AND review_basis IS NULL "
            "AND reviewed_by IS NULL AND reviewed_at IS NULL "
            "AND include_in_regression = false) "
            "OR (status = 'agreed' AND agreed = true AND corrected_passed IS NULL "
            "AND disagreement_dimension IS NULL AND review_basis IS NULL "
            "AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND include_in_regression = false) "
            "OR (status = 'corrected' AND agreed = false AND corrected_passed IS NOT NULL "
            "AND disagreement_dimension IS NOT NULL AND review_basis IS NOT NULL "
            "AND length(trim(review_basis)) > 0 AND reviewed_by IS NOT NULL "
            "AND reviewed_at IS NOT NULL AND include_in_regression = true)",
            name="ck_calibration_review_state",
        ),
        CheckConstraint(
            # SQLite length() counts characters. Migration 0011 uses MySQL CHAR_LENGTH().
            "review_basis IS NULL OR length(review_basis) <= 1000",
            name="ck_calibration_review_basis_length",
        ),
        CheckConstraint(
            "disagreement_dimension IS NULL OR disagreement_dimension IN "
            "('correctness', 'completeness', 'relevance', 'service_experience', "
            "'compliance', 'other')",
            name="ck_calibration_review_dimension",
        ),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[str] = uuid_primary_key()
    batch_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("calibration_batches.id", name="fk_calibration_review_batch"), nullable=False
    )
    evaluation_result_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("evaluation_results.id", name="fk_calibration_review_evaluation_result"),
        nullable=False,
    )
    selection_reason: Mapped[CalibrationSelectionReason] = mapped_column(
        enum_type(CalibrationSelectionReason), nullable=False
    )
    status: Mapped[CalibrationReviewStatus] = mapped_column(
        enum_type(CalibrationReviewStatus), default=CalibrationReviewStatus.PENDING, nullable=False
    )
    agreed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    corrected_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    disagreement_dimension: Mapped[CalibrationDimension | None] = mapped_column(
        enum_type(CalibrationDimension), nullable=True
    )
    review_basis: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    include_in_regression: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)

    evaluation_result: Mapped[EvaluationResult] = relationship()
