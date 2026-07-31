"""add quality standards

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-31 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

import app.shared.types
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quality_standards",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", app.shared.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at", app.shared.types.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_quality_standard_name"),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_table(
        "quality_standard_versions",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("standard_id", sa.CHAR(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_path", sa.String(length=512), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("published_at", app.shared.types.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["standard_id"],
            ["quality_standards.id"],
            name="fk_quality_standard_version_standard",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("standard_id", "version_number", name="uq_quality_standard_version"),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_table(
        "quality_standard_parse_jobs",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("standard_id", sa.CHAR(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", app.shared.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at", app.shared.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["standard_id"],
            ["quality_standards.id"],
            name="fk_quality_standard_parse_job_standard",
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )


def downgrade() -> None:
    op.drop_table("quality_standard_parse_jobs")
    op.drop_table("quality_standard_versions")
    op.drop_table("quality_standards")
