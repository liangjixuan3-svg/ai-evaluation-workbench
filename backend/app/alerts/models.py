from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CHAR, JSON, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.analysis.models import BadcaseCluster  # noqa: F401
from app.db import Base
from app.shared.enums import AlertStatus, RootCause, TaskStatus, TaskType
from app.shared.types import MYSQL_TABLE_ARGS, UTCDateTime, enum_type, utc_now, uuid_primary_key


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alert_status_merge", "status", "merge_key"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[str] = uuid_primary_key()
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[str] = mapped_column(String(8), nullable=False)
    scenario: Mapped[str | None] = mapped_column(String(128), nullable=True)
    root_cause: Mapped[RootCause | None] = mapped_column(enum_type(RootCause), nullable=True)
    status: Mapped[AlertStatus] = mapped_column(
        enum_type(AlertStatus), default=AlertStatus.OPEN, nullable=False
    )
    merge_key: Mapped[str] = mapped_column(String(255), nullable=False)
    baseline_value: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    current_value: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    impact_count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    window_ended_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )


class AlertResult(Base):
    __tablename__ = "alert_results"
    __table_args__ = MYSQL_TABLE_ARGS

    alert_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("alerts.id", name="fk_alert_result_alert"), primary_key=True
    )
    evaluation_result_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("evaluation_results.id", name="fk_alert_result_eval_result"),
        primary_key=True,
    )


class AlertSignalReceipt(Base):
    __tablename__ = "alert_signal_receipts"
    __table_args__ = MYSQL_TABLE_ARGS

    fingerprint: Mapped[str] = mapped_column(String(64), primary_key=True)
    alert_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("alerts.id", name="fk_alert_signal_receipt_alert"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("cluster_id", "type", name="uq_task_cluster_type"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[str] = uuid_primary_key()
    type: Mapped[TaskType] = mapped_column(enum_type(TaskType), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        enum_type(TaskStatus), default=TaskStatus.OPEN, nullable=False
    )
    alert_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("alerts.id", name="fk_task_alert"), nullable=True
    )
    cluster_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("badcase_clusters.id", name="fk_task_cluster"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    priority: Mapped[str] = mapped_column(String(8), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
