from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    JSON,
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.ingestion.models import Conversation, SamplingBatch
from app.shared.enums import Confidence, RunStatus
from app.shared.types import (
    MYSQL_TABLE_ARGS,
    UTCDateTime,
    enum_type,
    reject_immutable_change,
    utc_now,
    uuid_primary_key,
)


class EvaluationTemplate(Base):
    __tablename__ = "evaluation_templates"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_eval_template_name_version"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[str] = uuid_primary_key()
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    weights: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    threshold: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    veto_rules: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_prompt_name_version"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[str] = uuid_primary_key()
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class RuleVersion(Base):
    __tablename__ = "rule_versions"
    __table_args__ = (
        UniqueConstraint("kind", "version", name="uq_rule_kind_version"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[str] = uuid_primary_key()
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = MYSQL_TABLE_ARGS

    id: Mapped[str] = uuid_primary_key()
    sampling_batch_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("sampling_batches.id", name="fk_eval_run_sample_batch"), nullable=True
    )
    template_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("evaluation_templates.id", name="fk_eval_run_template"), nullable=False
    )
    prompt_version_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("prompt_versions.id", name="fk_eval_run_prompt"), nullable=False
    )
    rule_version_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("rule_versions.id", name="fk_eval_run_rule"), nullable=False
    )
    quality_standard_version_id: Mapped[str | None] = mapped_column(
        CHAR(36),
        ForeignKey(
            "quality_standard_versions.id", name="fk_eval_run_quality_standard_version"
        ),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    model_parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        enum_type(RunStatus), default=RunStatus.QUEUED, nullable=False
    )
    succeeded_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    sampling_batch: Mapped[SamplingBatch | None] = relationship()
    template: Mapped[EvaluationTemplate] = relationship()
    prompt_version: Mapped[PromptVersion] = relationship()
    rule_version: Mapped[RuleVersion] = relationship()
    quality_standard_version: Mapped[Any | None] = relationship("QualityStandardVersion")


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (
        UniqueConstraint("run_id", "conversation_id", name="uq_eval_result_run_conversation"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[str] = uuid_primary_key()
    run_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("evaluation_runs.id", name="fk_eval_result_run"), nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("conversations.id", name="fk_eval_result_conversation"), nullable=False
    )
    total_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    dimension_scores: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    confidence: Mapped[Confidence] = mapped_column(enum_type(Confidence), nullable=False)
    severe_factual_error: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    severe_compliance_error: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)

    run: Mapped[EvaluationRun] = relationship()
    conversation: Mapped[Conversation] = relationship()


class ModelCallRecord(Base):
    __tablename__ = "model_call_records"
    __table_args__ = MYSQL_TABLE_ARGS

    id: Mapped[str] = uuid_primary_key()
    evaluation_run_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("evaluation_runs.id", name="fk_model_call_eval_run"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)


event.listen(EvaluationResult, "before_update", reject_immutable_change)
event.listen(EvaluationResult, "before_delete", reject_immutable_change)
