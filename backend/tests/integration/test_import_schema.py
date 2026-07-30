from __future__ import annotations

import os

from sqlalchemy import create_engine, inspect


def test_import_session_schema_is_mysql_native() -> None:
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    try:
        inspector = inspect(engine)
        assert "import_sessions" in inspector.get_table_names()
        columns = inspector.get_columns("import_sessions")
        assert {column["name"] for column in columns} >= {
            "id",
            "filename",
            "file_hash",
            "status",
            "document",
            "candidate_paths",
            "mapping",
            "result_summary",
            "record_count",
            "error_count",
            "confirmed_source_id",
            "expires_at",
            "created_at",
            "confirmed_at",
        }
        document_type = next(column for column in columns if column["name"] == "document")[
            "type"
        ]
        assert type(document_type).__name__ == "JSON"
        constraints = inspector.get_unique_constraints("import_sessions")
        assert any(
            constraint["name"] == "uq_import_session_file_hash"
            and constraint["column_names"] == ["file_hash"]
            for constraint in constraints
        )
    finally:
        engine.dispose()
