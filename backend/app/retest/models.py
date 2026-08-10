from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CHAR, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.alerts.models import Alert  # noqa: F401
from app.db import Base
from app.evaluation.models import EvaluationResult, RuleVersion  # noqa: F401
from app.ingestion.models import Conversation  # noqa: F401
from app.remediation.models import QAVersion  # noqa: F401
from app.shared.enums import RetestCohort, RetestStatus
from app.shared.types import MYSQL_TABLE_ARGS, UTCDateTime, enum_type, utc_now, uuid_primary_key


class RetestRun(Base):
    __tablename__ = "retest_runs"
    __table_args__ = (
        UniqueConstraint("alert_id", "qa_version_id", name="uq_retest_run_alert_qa_version"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[str] = uuid_primary_key()
    alert_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("alerts.id", name="fk_retest_run_alert"), nullable=False
    )
    qa_version_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("qa_versions.id", name="fk_retest_run_qa_version"), nullable=True
    )
    rule_version_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("rule_versions.id", name="fk_retest_run_rule"), nullable=False
    )
    status: Mapped[RetestStatus] = mapped_column(
        enum_type(RetestStatus), default=RetestStatus.QUEUED, nullable=False
    )
    execution_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    before_pass_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    replay_pass_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    new_sample_pass_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class RetestSample(Base):
    __tablename__ = "retest_samples"
    __table_args__ = MYSQL_TABLE_ARGS

    retest_run_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("retest_runs.id", name="fk_retest_sample_run"), primary_key=True
    )
    conversation_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("conversations.id", name="fk_retest_sample_conversation"),
        primary_key=True,
    )
    cohort: Mapped[RetestCohort] = mapped_column(
        enum_type(RetestCohort), primary_key=True, nullable=False
    )
    source_evaluation_result_id: Mapped[str | None] = mapped_column(
        CHAR(36),
        ForeignKey("evaluation_results.id", name="fk_retest_sample_source_result"),
        nullable=True,
    )
    retest_evaluation_result_id: Mapped[str | None] = mapped_column(
        CHAR(36),
        ForeignKey("evaluation_results.id", name="fk_retest_sample_retest_result"),
        nullable=True,
    )
