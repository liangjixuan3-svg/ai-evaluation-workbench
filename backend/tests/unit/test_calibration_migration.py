from __future__ import annotations

from io import StringIO

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import mysql


def test_0011_compiles_mysql_character_length_and_dimension_constraints(monkeypatch) -> None:
    migration = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("0011").module
    output = StringIO()
    context = MigrationContext.configure(
        dialect=mysql.dialect(),
        opts={"as_sql": True, "output_buffer": output},
    )
    monkeypatch.setattr(migration, "op", Operations(context))

    migration.upgrade()

    sql = output.getvalue()
    assert "review_basis VARCHAR(1000)" in sql
    assert "CHAR_LENGTH(review_basis) <= 1000" in sql
    assert "completed_at DATETIME(6)" in sql
    assert "ck_calibration_review_dimension" in sql
    for dimension in (
        "correctness",
        "completeness",
        "relevance",
        "service_experience",
        "compliance",
        "other",
    ):
        assert f"'{dimension}'" in sql
    assert "'tone'" not in sql
