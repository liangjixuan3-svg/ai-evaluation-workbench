"""bind evaluation runs to quality standard versions

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evaluation_runs",
        sa.Column("quality_standard_version_id", sa.CHAR(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_eval_run_quality_standard_version",
        "evaluation_runs",
        "quality_standard_versions",
        ["quality_standard_version_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_eval_run_quality_standard_version", "evaluation_runs", type_="foreignkey"
    )
    op.drop_column("evaluation_runs", "quality_standard_version_id")
