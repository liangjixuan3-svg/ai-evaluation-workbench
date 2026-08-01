from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory


def _migration():
    return ScriptDirectory.from_config(Config("alembic.ini")).get_revision("0006").module


def test_0006_adds_nullable_upload_dedup_key(monkeypatch) -> None:
    migration = _migration()
    calls: list[tuple[str, object]] = []

    class RecordingOperations:
        def add_column(self, table_name: str, column) -> None:
            calls.append(("add_column", (table_name, column)))

        def create_unique_constraint(self, name: str, table_name: str, columns) -> None:
            calls.append(("create_unique_constraint", (name, table_name, columns)))

    monkeypatch.setattr(migration, "op", RecordingOperations())

    migration.upgrade()

    column = calls[0][1][1]
    assert calls[0][0] == "add_column"
    assert calls[0][1][0] == "quality_standard_versions"
    assert column.name == "upload_dedup_key"
    assert column.nullable is True
    assert calls[1] == (
        "create_unique_constraint",
        (
            "uq_quality_standard_version_upload_dedup_key",
            "quality_standard_versions",
            ["upload_dedup_key"],
        ),
    )


def test_0006_downgrade_removes_constraint_before_column(monkeypatch) -> None:
    migration = _migration()
    calls: list[tuple[str, object]] = []

    class RecordingOperations:
        def drop_constraint(self, name: str, table_name: str, type_: str) -> None:
            calls.append(("drop_constraint", (name, table_name, type_)))

        def drop_column(self, table_name: str, column_name: str) -> None:
            calls.append(("drop_column", (table_name, column_name)))

    monkeypatch.setattr(migration, "op", RecordingOperations())

    migration.downgrade()

    assert calls == [
        (
            "drop_constraint",
            (
                "uq_quality_standard_version_upload_dedup_key",
                "quality_standard_versions",
                "unique",
            ),
        ),
        ("drop_column", ("quality_standard_versions", "upload_dedup_key")),
    ]
