from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.evaluation.models import EvaluationResult, EvaluationRun  # noqa: F401
from app.shared.enums import Confidence, RootCause
from app.shared.types import MYSQL_TABLE_ARGS, UTCDateTime, enum_type, utc_now, uuid_primary_key


class BadcaseCluster(Base):
    __tablename__ = "badcase_clusters"
    __table_args__ = MYSQL_TABLE_ARGS

    id: Mapped[str] = uuid_primary_key()
    run_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("evaluation_runs.id", name="fk_badcase_cluster_run"), nullable=False
    )
    scenario: Mapped[str | None] = mapped_column(String(128), nullable=True)
    weakest_dimension: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_reason: Mapped[str] = mapped_column(Text, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)


class ClusterMember(Base):
    __tablename__ = "cluster_members"
    __table_args__ = MYSQL_TABLE_ARGS

    cluster_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("badcase_clusters.id", name="fk_cluster_member_cluster"),
        primary_key=True,
    )
    evaluation_result_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("evaluation_results.id", name="fk_cluster_member_result"),
        primary_key=True,
    )
    representative_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmed_root_cause: Mapped[RootCause | None] = mapped_column(
        enum_type(RootCause), nullable=True
    )
    confirmed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class RootCauseSuggestion(Base):
    __tablename__ = "root_cause_suggestions"
    __table_args__ = MYSQL_TABLE_ARGS

    id: Mapped[str] = uuid_primary_key()
    cluster_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("badcase_clusters.id", name="fk_root_suggestion_cluster"),
        nullable=False,
    )
    root_cause: Mapped[RootCause] = mapped_column(enum_type(RootCause), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    confidence: Mapped[Confidence] = mapped_column(enum_type(Confidence), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
