from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError


def test_quality_standard_schema_is_mysql_native() -> None:
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    try:
        inspector = inspect(engine)
        expected_columns = {
            "quality_standards": {"id", "name", "status", "created_at", "updated_at"},
            "quality_standard_versions": {
                "id",
                "standard_id",
                "version_number",
                "source_filename",
                "source_sha256",
                "source_path",
                "rules",
                "published_at",
            },
            "quality_standard_parse_jobs": {
                "id",
                "standard_id",
                "status",
                "error_summary",
                "attempts",
                "created_at",
                "updated_at",
            },
        }
        actual_columns = {
            table_name: {column["name"] for column in inspector.get_columns(table_name)}
            for table_name in expected_columns
            if table_name in inspector.get_table_names()
        }
        assert set(actual_columns) == set(expected_columns)
        for table_name, columns in expected_columns.items():
            assert columns <= actual_columns[table_name]

        with engine.connect() as connection:
            tables = connection.execute(
                text(
                    "SELECT TABLE_NAME, ENGINE, TABLE_COLLATION "
                    "FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() "
                    "AND TABLE_NAME IN ('quality_standards', 'quality_standard_versions', "
                    "'quality_standard_parse_jobs')"
                )
            ).mappings()
            table_options = {item["TABLE_NAME"]: item for item in tables}

        assert set(table_options) == set(expected_columns)
        assert {item["ENGINE"] for item in table_options.values()} == {"InnoDB"}
        assert all(item["TABLE_COLLATION"].startswith("utf8mb4_") for item in table_options.values())

        rules_column = next(
            column
            for column in inspector.get_columns("quality_standard_versions")
            if column["name"] == "rules"
        )
        assert type(rules_column["type"]).__name__ == "JSON"

        standard_constraints = inspector.get_unique_constraints("quality_standards")
        version_constraints = inspector.get_unique_constraints("quality_standard_versions")
        assert any(
            item["name"] == "uq_quality_standard_name" and item["column_names"] == ["name"]
            for item in standard_constraints
        )
        assert any(
            item["name"] == "uq_quality_standard_version"
            and item["column_names"] == ["standard_id", "version_number"]
            for item in version_constraints
        )

        for table_name, foreign_key_name in {
            "quality_standard_versions": "fk_quality_standard_version_standard",
            "quality_standard_parse_jobs": "fk_quality_standard_parse_job_standard",
        }.items():
            foreign_keys = inspector.get_foreign_keys(table_name)
            assert any(
                item["name"] == foreign_key_name
                and item["referred_table"] == "quality_standards"
                and item["constrained_columns"] == ["standard_id"]
                for item in foreign_keys
            )
    finally:
        engine.dispose()


def test_published_version_triggers_block_bulk_update_and_delete() -> None:
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    standard_id = str(uuid4())
    version_id = str(uuid4())
    try:
        with engine.connect() as connection:
            triggers = connection.execute(
                text(
                    "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS "
                    "WHERE TRIGGER_SCHEMA = DATABASE() AND EVENT_OBJECT_TABLE = "
                    "'quality_standard_versions'"
                )
            ).scalars()
            assert set(triggers) >= {
                "trg_quality_standard_versions_immutable_update",
                "trg_quality_standard_versions_immutable_delete",
            }

        with engine.begin() as connection:
            now = datetime.now(UTC)
            connection.execute(
                text(
                    "INSERT INTO quality_standards "
                    "(id, name, status, created_at, updated_at) "
                    "VALUES (:id, :name, 'published', :now, :now)"
                ),
                {"id": standard_id, "name": f"trigger-test-{standard_id}", "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO quality_standard_versions "
                    "(id, standard_id, version_number, source_filename, source_sha256, "
                    "source_path, rules, published_at) VALUES "
                    "(:id, :standard_id, 1, 'standard.docx', :sha256, :path, :rules, :now)"
                ),
                {
                    "id": version_id,
                    "standard_id": standard_id,
                    "sha256": "a" * 64,
                    "path": "quality-standards/standard.docx",
                    "rules": json.dumps({"validated": True}),
                    "now": now,
                },
            )

        with pytest.raises(DBAPIError, match="immutable"), engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE quality_standard_versions SET source_path = 'bypassed.docx' "
                    "WHERE id = :id"
                ),
                {"id": version_id},
            )

        with pytest.raises(DBAPIError, match="immutable"), engine.begin() as connection:
            connection.execute(
                text("DELETE FROM quality_standard_versions WHERE id = :id"),
                {"id": version_id},
            )
    finally:
        engine.dispose()
