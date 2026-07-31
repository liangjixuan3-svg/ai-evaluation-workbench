from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory


def _migration():
    return ScriptDirectory.from_config(Config("alembic.ini")).get_revision("0005").module


def test_0005_installs_guards_for_bulk_update_and_delete(monkeypatch) -> None:
    migration = _migration()
    statements: list[str] = []

    class RecordingOperations:
        def create_table(self, *args, **kwargs) -> None:
            pass

        def execute(self, statement) -> None:
            statements.append(str(statement))

    monkeypatch.setattr(migration, "op", RecordingOperations())

    migration.upgrade()

    assert len(statements) == 2
    assert "BEFORE UPDATE" in statements[0]
    assert "OLD.published_at IS NOT NULL" in statements[0]
    assert "SIGNAL SQLSTATE '45000'" in statements[0]
    assert "BEFORE DELETE" in statements[1]
    assert "OLD.published_at IS NOT NULL" in statements[1]
    assert "SIGNAL SQLSTATE '45000'" in statements[1]


def test_0005_downgrade_removes_guards_before_tables(monkeypatch) -> None:
    migration = _migration()
    calls: list[tuple[str, str]] = []

    class RecordingOperations:
        def execute(self, statement) -> None:
            calls.append(("execute", str(statement)))

        def drop_table(self, table_name: str) -> None:
            calls.append(("drop_table", table_name))

    monkeypatch.setattr(migration, "op", RecordingOperations())

    migration.downgrade()

    assert calls[:2] == [
        ("execute", "DROP TRIGGER IF EXISTS trg_quality_standard_versions_immutable_update"),
        ("execute", "DROP TRIGGER IF EXISTS trg_quality_standard_versions_immutable_delete"),
    ]
    assert calls[2:] == [
        ("drop_table", "quality_standard_parse_jobs"),
        ("drop_table", "quality_standard_versions"),
        ("drop_table", "quality_standards"),
    ]
