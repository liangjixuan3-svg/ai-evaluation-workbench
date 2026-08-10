"""add evaluation calibration records

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa

import app.shared.types
from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calibration_batches",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("batch_date", sa.Date(), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", app.shared.types.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_date", name="uq_calibration_batch_date"),
        sa.CheckConstraint("target_count BETWEEN 1 AND 20", name="ck_calibration_batch_target_count"),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_table(
        "calibration_reviews",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("batch_id", sa.CHAR(length=36), nullable=False),
        sa.Column("evaluation_result_id", sa.CHAR(length=36), nullable=False),
        sa.Column("selection_reason", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("agreed", sa.Boolean(), nullable=True),
        sa.Column("corrected_passed", sa.Boolean(), nullable=True),
        sa.Column("disagreement_dimension", sa.String(length=32), nullable=True),
        sa.Column("review_basis", sa.String(length=1000), nullable=True),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", app.shared.types.UTCDateTime(), nullable=True),
        sa.Column("include_in_regression", sa.Boolean(), nullable=False),
        sa.Column("created_at", app.shared.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["calibration_batches.id"], name="fk_calibration_review_batch"
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_result_id"],
            ["evaluation_results.id"],
            name="fk_calibration_review_evaluation_result",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evaluation_result_id", name="uq_calibration_review_evaluation_result"
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND agreed IS NULL AND corrected_passed IS NULL "
            "AND disagreement_dimension IS NULL AND review_basis IS NULL "
            "AND reviewed_by IS NULL AND reviewed_at IS NULL "
            "AND include_in_regression = false) "
            "OR (status = 'agreed' AND agreed = true AND corrected_passed IS NULL "
            "AND disagreement_dimension IS NULL AND review_basis IS NULL "
            "AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND include_in_regression = false) "
            "OR (status = 'corrected' AND agreed = false AND corrected_passed IS NOT NULL "
            "AND disagreement_dimension IS NOT NULL AND review_basis IS NOT NULL "
            "AND length(trim(review_basis)) > 0 AND reviewed_by IS NOT NULL "
            "AND reviewed_at IS NOT NULL AND include_in_regression = true)",
            name="ck_calibration_review_state",
        ),
        sa.CheckConstraint(
            "review_basis IS NULL OR length(review_basis) <= 1000",
            name="ck_calibration_review_basis_length",
        ),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_calibration_review_batch_status", "calibration_reviews", ["batch_id", "status"]
    )
    op.create_index("ix_calibration_review_regression", "calibration_reviews", ["include_in_regression"])


def downgrade() -> None:
    op.drop_table("calibration_reviews")
    op.drop_table("calibration_batches")
