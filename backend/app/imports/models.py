from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.ingestion.models import DataSource  # noqa: F401
from app.shared.types import MYSQL_TABLE_ARGS, UTCDateTime, utc_now, uuid_primary_key


class ImportSession(Base):
    __tablename__ = "import_sessions"
    __table_args__ = (
        UniqueConstraint("file_hash", name="uq_import_session_file_hash"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[str] = uuid_primary_key()
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    document: Mapped[Any] = mapped_column(JSON, nullable=False)
    candidate_paths: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    mapping: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confirmed_source_id: Mapped[str | None] = mapped_column(
        CHAR(36),
        ForeignKey("data_sources.id", name="fk_import_session_source"),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
