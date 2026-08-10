from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CHAR, Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.shared.enums import (
    CalibrationBatchStatus,
    CalibrationDimension,
    CalibrationReviewStatus,
    CalibrationSelectionReason,
)
from app.shared.types import MYSQL_TABLE_ARGS, UTCDateTime, enum_type, utc_now, uuid_primary_key


class CalibrationBatch(Base):
    __tablename__ = "calibration_batches"
    __table_args__ = (
        UniqueConstraint("batch_date", name="uq_calibration_batch_date"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[str] = uuid_primary_key()
    batch_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[CalibrationBatchStatus] = mapped_column(
        enum_type(CalibrationBatchStatus), default=CalibrationBatchStatus.OPEN, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)


class CalibrationReview(Base):
    __tablename__ = "calibration_reviews"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_result_id", name="uq_calibration_review_evaluation_result"
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
    review_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    include_in_regression: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
