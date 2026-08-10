"""ensure one retest run per published QA version

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, alert_id, qa_version_id FROM retest_runs "
            "WHERE qa_version_id IS NOT NULL ORDER BY created_at, id"
        )
    ).mappings()
    seen: set[tuple[str, str]] = set()
    duplicate_ids: list[str] = []
    for row in rows:
        key = (row["alert_id"], row["qa_version_id"])
        if key in seen:
            duplicate_ids.append(row["id"])
        else:
            seen.add(key)
    for run_id in duplicate_ids:
        connection.execute(
            sa.text("DELETE FROM retest_samples WHERE retest_run_id = :run_id"),
            {"run_id": run_id},
        )
        connection.execute(
            sa.text("DELETE FROM retest_runs WHERE id = :run_id"),
            {"run_id": run_id},
        )
    op.create_unique_constraint(
        "uq_retest_run_alert_qa_version",
        "retest_runs",
        ["alert_id", "qa_version_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_retest_run_alert_qa_version",
        "retest_runs",
        type_="unique",
    )
