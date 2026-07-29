"""add remediation replay constraints

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-30 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TASK_CLUSTER_INDEX = "ix_task_cluster_id"
_QA_DRAFT_TASK_INDEX = "ix_qa_draft_task_id"


def _index_exists(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    )


def upgrade() -> None:
    op.create_unique_constraint("uq_task_cluster_type", "tasks", ["cluster_id", "type"])
    op.create_unique_constraint("uq_qa_draft_task", "qa_drafts", ["task_id"])
    op.create_unique_constraint(
        "uq_export_record_format_hash", "export_records", ["format", "artifact_hash"]
    )
    if _index_exists("tasks", _TASK_CLUSTER_INDEX):
        op.drop_index(_TASK_CLUSTER_INDEX, table_name="tasks")
    if _index_exists("qa_drafts", _QA_DRAFT_TASK_INDEX):
        op.drop_index(_QA_DRAFT_TASK_INDEX, table_name="qa_drafts")


def downgrade() -> None:
    if not _index_exists("tasks", _TASK_CLUSTER_INDEX):
        op.create_index(_TASK_CLUSTER_INDEX, "tasks", ["cluster_id"], unique=False)
    if not _index_exists("qa_drafts", _QA_DRAFT_TASK_INDEX):
        op.create_index(_QA_DRAFT_TASK_INDEX, "qa_drafts", ["task_id"], unique=False)
    op.drop_constraint("uq_export_record_format_hash", "export_records", type_="unique")
    op.drop_constraint("uq_qa_draft_task", "qa_drafts", type_="unique")
    op.drop_constraint("uq_task_cluster_type", "tasks", type_="unique")
