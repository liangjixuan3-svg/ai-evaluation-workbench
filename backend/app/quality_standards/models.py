from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    JSON,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db import Base
from app.quality_standards.contracts import QualityStandardRules
from app.shared.types import (
    MYSQL_TABLE_ARGS,
    ImmutableRecordError,
    UTCDateTime,
    utc_now,
    uuid_primary_key,
)


class QualityStandard(Base):
    __tablename__ = "quality_standards"
    __table_args__ = (UniqueConstraint("name", name="uq_quality_standard_name"), MYSQL_TABLE_ARGS)

    id: Mapped[str] = uuid_primary_key()
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    versions: Mapped[list[QualityStandardVersion]] = relationship(
        back_populates="standard", cascade="all, delete-orphan"
    )
    parse_jobs: Mapped[list[QualityStandardParseJob]] = relationship(
        back_populates="standard", cascade="all, delete-orphan"
    )


class QualityStandardVersion(Base):
    __tablename__ = "quality_standard_versions"
    __table_args__ = (
        UniqueConstraint("standard_id", "version_number", name="uq_quality_standard_version"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[str] = uuid_primary_key()
    standard_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("quality_standards.id", name="fk_quality_standard_version_standard"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_path: Mapped[str] = mapped_column(String(512), nullable=False)
    rules: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    standard: Mapped[QualityStandard] = relationship(back_populates="versions")

    @validates("rules")
    def validate_rules(self, key: str, value: object) -> dict[str, Any]:
        return _validated_rules(value)


class QualityStandardParseJob(Base):
    __tablename__ = "quality_standard_parse_jobs"
    __table_args__ = MYSQL_TABLE_ARGS

    id: Mapped[str] = uuid_primary_key()
    standard_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("quality_standards.id", name="fk_quality_standard_parse_job_standard"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    standard: Mapped[QualityStandard] = relationship(back_populates="parse_jobs")


def _validated_rules(value: object) -> dict[str, Any]:
    return QualityStandardRules.model_validate(value).model_dump(mode="json")


def validate_version_rules_before_write(
    mapper: object, connection: object, target: QualityStandardVersion
) -> None:
    target.rules = _validated_rules(target.rules)


def reject_published_version_change(mapper: object, connection: object, target: object) -> None:
    published_at = inspect(target).attrs.published_at.history
    if any(value is not None for value in published_at.deleted):
        raise ImmutableRecordError("published quality standard versions are immutable")
    if not published_at.added and target.published_at is not None:
        raise ImmutableRecordError("published quality standard versions are immutable")


def reject_published_version_delete(mapper: object, connection: object, target: QualityStandardVersion) -> None:
    if target.published_at is not None:
        raise ImmutableRecordError("published quality standard versions are immutable")


event.listen(QualityStandardVersion, "before_insert", validate_version_rules_before_write)
event.listen(QualityStandardVersion, "before_update", validate_version_rules_before_write)
event.listen(QualityStandardVersion, "before_update", reject_published_version_change)
event.listen(QualityStandardVersion, "before_delete", reject_published_version_delete)
