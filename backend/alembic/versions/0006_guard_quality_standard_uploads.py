"""guard quality standard uploads

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Historical rows may contain duplicate hashes. A nullable key preserves those
    # records while enforcing idempotency for every upload created after this migration.
    op.add_column(
        "quality_standard_versions",
        sa.Column("upload_dedup_key", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        "uq_quality_standard_version_upload_dedup_key",
        "quality_standard_versions",
        ["upload_dedup_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_quality_standard_version_upload_dedup_key",
        "quality_standard_versions",
        type_="unique",
    )
    op.drop_column("quality_standard_versions", "upload_dedup_key")
