from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.shared.enums import RunStatus
from app.shared.types import MYSQL_TABLE_ARGS, UTCDateTime, enum_type, utc_now, uuid_primary_key


class DataSource(Base):
    __tablename__ = "data_sources"
    __table_args__ = (UniqueConstraint("name", name="uq_data_source_name"), MYSQL_TABLE_ARGS)

    id: Mapped[str] = uuid_primary_key()
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    conversations: Mapped[list[Conversation]] = relationship(back_populates="data_source")


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("data_source_id", "external_id", name="uq_conversation_source_external"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[str] = uuid_primary_key()
    data_source_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("data_sources.id", name="fk_conversation_source"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    scenario: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    body: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)

    data_source: Mapped[DataSource] = relationship(back_populates="conversations")


class SamplingBatch(Base):
    __tablename__ = "sampling_batches"
    __table_args__ = MYSQL_TABLE_ARGS

    id: Mapped[str] = uuid_primary_key()
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        enum_type(RunStatus), default=RunStatus.QUEUED, nullable=False
    )
    selected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class SamplingBatchConversation(Base):
    __tablename__ = "sampling_batch_conversations"
    __table_args__ = MYSQL_TABLE_ARGS

    batch_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("sampling_batches.id", name="fk_sample_member_batch"),
        primary_key=True,
    )
    conversation_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("conversations.id", name="fk_sample_member_conversation"),
        primary_key=True,
    )
    selection_reason: Mapped[str] = mapped_column(String(128), nullable=False)
