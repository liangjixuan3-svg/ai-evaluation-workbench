"""add JSON import sessions

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-30 16:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

import app.shared.types
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_sessions",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("candidate_paths", sa.JSON(), nullable=False),
        sa.Column("mapping", sa.JSON(), nullable=False),
        sa.Column("result_summary", sa.JSON(), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("confirmed_source_id", sa.CHAR(length=36), nullable=True),
        sa.Column("expires_at", app.shared.types.UTCDateTime(), nullable=False),
        sa.Column("created_at", app.shared.types.UTCDateTime(), nullable=False),
        sa.Column("confirmed_at", app.shared.types.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["confirmed_source_id"],
            ["data_sources.id"],
            name="fk_import_session_source",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_hash", name="uq_import_session_file_hash"),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )


def downgrade() -> None:
    op.drop_table("import_sessions")
