from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import CHAR, DateTime
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import MappedColumn, mapped_column
from sqlalchemy.types import TypeDecorator

MYSQL_TABLE_ARGS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def new_uuid() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Any):
        if dialect.name == "mysql":
            return dialect.type_descriptor(DATETIME(fsp=6))
        return dialect.type_descriptor(DateTime(timezone=False))

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("UTCDateTime requires a timezone-aware datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class ImmutableRecordError(RuntimeError):
    pass


def reject_immutable_change(mapper: Any, connection: Any, target: Any) -> None:
    raise ImmutableRecordError(f"{type(target).__name__} rows are immutable")


def uuid_primary_key() -> MappedColumn[str]:
    return mapped_column(CHAR(36), primary_key=True, default=new_uuid)


def enum_type(enum_class: type[StrEnum]) -> SQLAlchemyEnum:
    return SQLAlchemyEnum(
        enum_class,
        native_enum=False,
        length=32,
        values_callable=lambda values: [item.value for item in values],
        validate_strings=True,
        name=f"{enum_class.__name__.lower()}_values",
    )
