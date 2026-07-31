from __future__ import annotations

import os

from sqlalchemy import create_engine, inspect, text


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
        assert expected_columns <= {
            table_name: {column["name"] for column in inspector.get_columns(table_name)}
            for table_name in expected_columns
            if table_name in inspector.get_table_names()
        }

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
