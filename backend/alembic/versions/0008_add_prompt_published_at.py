"""add evaluation prompt publication time

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa

import app.shared.types
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "prompt_versions",
        sa.Column("published_at", app.shared.types.UTCDateTime(), nullable=True),
    )
    op.execute("UPDATE prompt_versions SET published_at = created_at")


def downgrade() -> None:
    op.drop_column("prompt_versions", "published_at")
