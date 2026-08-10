"""add retest execution fencing token

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("retest_runs", sa.Column("execution_token", sa.String(36), nullable=True))


def downgrade() -> None:
    op.drop_column("retest_runs", "execution_token")
