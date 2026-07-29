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
    _deduplicate_legacy_rows()
    op.create_unique_constraint("uq_task_cluster_type", "tasks", ["cluster_id", "type"])
    op.create_unique_constraint("uq_qa_draft_task", "qa_drafts", ["task_id"])
    op.create_unique_constraint(
        "uq_export_record_format_hash", "export_records", ["format", "artifact_hash"]
    )
    if _index_exists("tasks", _TASK_CLUSTER_INDEX):
        op.drop_index(_TASK_CLUSTER_INDEX, table_name="tasks")
    if _index_exists("qa_drafts", _QA_DRAFT_TASK_INDEX):
        op.drop_index(_QA_DRAFT_TASK_INDEX, table_name="qa_drafts")


def _deduplicate_legacy_rows() -> None:
    _deduplicate_tasks()
    _deduplicate_qa_drafts()
    _deduplicate_exports()


def _deduplicate_tasks() -> None:
    bind = op.get_bind()
    groups = list(
        bind.execute(
            sa.text(
                "SELECT cluster_id, type FROM tasks WHERE cluster_id IS NOT NULL "
                "GROUP BY cluster_id, type HAVING COUNT(*) > 1"
            )
        ).mappings()
    )
    for group in groups:
        task_ids = list(
            bind.execute(
                sa.text(
                    "SELECT id FROM tasks WHERE cluster_id = :cluster_id AND type = :type "
                    "ORDER BY created_at, id"
                ),
                {"cluster_id": group["cluster_id"], "type": group["type"]},
            ).scalars()
        )
        canonical_id = task_ids[0]
        for duplicate_id in task_ids[1:]:
            bind.execute(
                sa.text(
                    "UPDATE qa_drafts SET task_id = :canonical_id WHERE task_id = :duplicate_id"
                ),
                {"canonical_id": canonical_id, "duplicate_id": duplicate_id},
            )
            _redirect_audits(bind, "task", duplicate_id, canonical_id)
            bind.execute(
                sa.text("DELETE FROM tasks WHERE id = :duplicate_id"),
                {"duplicate_id": duplicate_id},
            )


def _deduplicate_qa_drafts() -> None:
    bind = op.get_bind()
    task_ids = list(
        bind.execute(
            sa.text(
                "SELECT task_id FROM qa_drafts WHERE task_id IS NOT NULL "
                "GROUP BY task_id HAVING COUNT(*) > 1"
            )
        ).scalars()
    )
    for task_id in task_ids:
        draft_ids = list(
            bind.execute(
                sa.text(
                    "SELECT id FROM qa_drafts WHERE task_id = :task_id ORDER BY created_at, id"
                ),
                {"task_id": task_id},
            ).scalars()
        )
        canonical_id = draft_ids[0]
        next_version_number = bind.execute(
            sa.text(
                "SELECT GREATEST(d.current_version_number, "
                "COALESCE(MAX(v.version_number), 0)) FROM qa_drafts AS d "
                "LEFT JOIN qa_versions AS v ON v.draft_id = d.id "
                "WHERE d.id = :draft_id GROUP BY d.current_version_number"
            ),
            {"draft_id": canonical_id},
        ).scalar_one()
        for duplicate_id in draft_ids[1:]:
            version_ids = list(
                bind.execute(
                    sa.text(
                        "SELECT id FROM qa_versions WHERE draft_id = :draft_id "
                        "ORDER BY version_number, created_at, id"
                    ),
                    {"draft_id": duplicate_id},
                ).scalars()
            )
            for version_id in version_ids:
                next_version_number += 1
                bind.execute(
                    sa.text(
                        "UPDATE qa_versions SET draft_id = :canonical_id, "
                        "version_number = :version_number WHERE id = :version_id"
                    ),
                    {
                        "canonical_id": canonical_id,
                        "version_number": next_version_number,
                        "version_id": version_id,
                    },
                )
            _redirect_audits(bind, "qa_draft", duplicate_id, canonical_id)
            bind.execute(
                sa.text("DELETE FROM qa_drafts WHERE id = :duplicate_id"),
                {"duplicate_id": duplicate_id},
            )
        bind.execute(
            sa.text(
                "UPDATE qa_drafts SET current_version_number = :version_number WHERE id = :draft_id"
            ),
            {"version_number": next_version_number, "draft_id": canonical_id},
        )


def _deduplicate_exports() -> None:
    bind = op.get_bind()
    groups = list(
        bind.execute(
            sa.text(
                "SELECT format, artifact_hash FROM export_records "
                "GROUP BY format, artifact_hash HAVING COUNT(*) > 1"
            )
        ).mappings()
    )
    for group in groups:
        export_ids = list(
            bind.execute(
                sa.text(
                    "SELECT id FROM export_records WHERE format = :format "
                    "AND artifact_hash = :artifact_hash ORDER BY created_at, id"
                ),
                {"format": group["format"], "artifact_hash": group["artifact_hash"]},
            ).scalars()
        )
        canonical_id = export_ids[0]
        for duplicate_id in export_ids[1:]:
            bind.execute(
                sa.text(
                    "INSERT IGNORE INTO qa_export_items (export_id, qa_version_id) "
                    "SELECT :canonical_id, qa_version_id FROM qa_export_items "
                    "WHERE export_id = :duplicate_id"
                ),
                {"canonical_id": canonical_id, "duplicate_id": duplicate_id},
            )
            bind.execute(
                sa.text("DELETE FROM qa_export_items WHERE export_id = :duplicate_id"),
                {"duplicate_id": duplicate_id},
            )
            _redirect_audits(bind, "export_record", duplicate_id, canonical_id)
            bind.execute(
                sa.text("DELETE FROM export_records WHERE id = :duplicate_id"),
                {"duplicate_id": duplicate_id},
            )


def _redirect_audits(bind: sa.Connection, entity_type: str, old_id: str, new_id: str) -> None:
    bind.execute(
        sa.text(
            "UPDATE audit_events SET entity_id = :new_id "
            "WHERE entity_type = :entity_type AND entity_id = :old_id"
        ),
        {"new_id": new_id, "entity_type": entity_type, "old_id": old_id},
    )


def downgrade() -> None:
    if not _index_exists("tasks", _TASK_CLUSTER_INDEX):
        op.create_index(_TASK_CLUSTER_INDEX, "tasks", ["cluster_id"], unique=False)
    if not _index_exists("qa_drafts", _QA_DRAFT_TASK_INDEX):
        op.create_index(_QA_DRAFT_TASK_INDEX, "qa_drafts", ["task_id"], unique=False)
    op.drop_constraint("uq_export_record_format_hash", "export_records", type_="unique")
    op.drop_constraint("uq_qa_draft_task", "qa_drafts", type_="unique")
    op.drop_constraint("uq_task_cluster_type", "tasks", type_="unique")
