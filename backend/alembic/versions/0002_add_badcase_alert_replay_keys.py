"""add badcase and alert replay keys

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-30 04:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

import app.shared.types
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "badcase_clusters", sa.Column("grouping_key", sa.String(length=64), nullable=True)
    )
    op.create_unique_constraint("uq_badcase_cluster_grouping", "badcase_clusters", ["grouping_key"])
    op.add_column(
        "root_cause_suggestions",
        sa.Column("evaluation_result_id", sa.CHAR(length=36), nullable=True),
    )
    op.add_column(
        "root_cause_suggestions", sa.Column("provider", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "root_cause_suggestions", sa.Column("model", sa.String(length=128), nullable=True)
    )
    op.create_foreign_key(
        "fk_root_suggestion_result",
        "root_cause_suggestions",
        "evaluation_results",
        ["evaluation_result_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_root_suggestion_replay",
        "root_cause_suggestions",
        ["cluster_id", "provider", "model", "evaluation_result_id"],
    )
    op.create_table(
        "alert_signal_receipts",
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("alert_id", sa.CHAR(length=36), nullable=False),
        sa.Column("created_at", app.shared.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], name="fk_alert_signal_receipt_alert"),
        sa.PrimaryKeyConstraint("fingerprint"),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )


def downgrade() -> None:
    op.drop_table("alert_signal_receipts")
    op.drop_constraint("uq_root_suggestion_replay", "root_cause_suggestions", type_="unique")
    op.drop_constraint("fk_root_suggestion_result", "root_cause_suggestions", type_="foreignkey")
    op.drop_column("root_cause_suggestions", "model")
    op.drop_column("root_cause_suggestions", "provider")
    op.drop_column("root_cause_suggestions", "evaluation_result_id")
    op.drop_constraint("uq_badcase_cluster_grouping", "badcase_clusters", type_="unique")
    op.drop_column("badcase_clusters", "grouping_key")
