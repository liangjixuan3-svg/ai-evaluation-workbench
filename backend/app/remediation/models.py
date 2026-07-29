from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, JSON, ForeignKey, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.alerts.models import Task  # noqa: F401
from app.analysis.models import BadcaseCluster
from app.db import Base
from app.evaluation.models import EvaluationResult  # noqa: F401
from app.ingestion.models import Conversation  # noqa: F401
from app.shared.enums import Confidence, QADraftStatus
from app.shared.types import (
    MYSQL_TABLE_ARGS,
    UTCDateTime,
    enum_type,
    reject_immutable_change,
    utc_now,
    uuid_primary_key,
)


class QADraft(Base):
    __tablename__ = "qa_drafts"
    __table_args__ = MYSQL_TABLE_ARGS

    id: Mapped[str] = uuid_primary_key()
    cluster_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("badcase_clusters.id", name="fk_qa_draft_cluster"), nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("tasks.id", name="fk_qa_draft_task"), nullable=True
    )
    status: Mapped[QADraftStatus] = mapped_column(
        enum_type(QADraftStatus), default=QADraftStatus.DRAFT, nullable=False
    )
    current_version_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence: Mapped[Confidence] = mapped_column(enum_type(Confidence), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    cluster: Mapped[BadcaseCluster] = relationship()


class QAVersion(Base):
    __tablename__ = "qa_versions"
    __table_args__ = (
        UniqueConstraint("draft_id", "version_number", name="uq_qa_version_draft_number"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[str] = uuid_primary_key()
    draft_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("qa_drafts.id", name="fk_qa_version_draft"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)

    draft: Mapped[QADraft] = relationship()


class QAEvidence(Base):
    __tablename__ = "qa_evidence"
    __table_args__ = MYSQL_TABLE_ARGS

    id: Mapped[str] = uuid_primary_key()
    qa_version_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("qa_versions.id", name="fk_qa_evidence_version"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("conversations.id", name="fk_qa_evidence_conversation"), nullable=True
    )
    evaluation_result_id: Mapped[str | None] = mapped_column(
        CHAR(36),
        ForeignKey("evaluation_results.id", name="fk_qa_evidence_eval_result"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)


class ExportRecord(Base):
    __tablename__ = "export_records"
    __table_args__ = MYSQL_TABLE_ARGS

    id: Mapped[str] = uuid_primary_key()
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    artifact_path: Mapped[str] = mapped_column(String(512), nullable=False)
    artifact_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)


class QAExportItem(Base):
    __tablename__ = "qa_export_items"
    __table_args__ = MYSQL_TABLE_ARGS

    export_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("export_records.id", name="fk_qa_export_item_export"), primary_key=True
    )
    qa_version_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("qa_versions.id", name="fk_qa_export_item_version"), primary_key=True
    )


event.listen(QAVersion, "before_update", reject_immutable_change)
event.listen(QAVersion, "before_delete", reject_immutable_change)
