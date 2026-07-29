"""add badcase and alert replay keys

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-30 04:20:00.000000

"""

import hashlib
import json
from collections.abc import Sequence

import sqlalchemy as sa

import app.shared.types
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROOT_SUGGESTION_CLUSTER_INDEX = "ix_root_suggestion_cluster_id"


def upgrade() -> None:
    op.add_column(
        "badcase_clusters", sa.Column("grouping_key", sa.String(length=64), nullable=True)
    )
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
    _backfill_replay_keys()
    op.alter_column(
        "badcase_clusters",
        "grouping_key",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.alter_column(
        "root_cause_suggestions",
        "evaluation_result_id",
        existing_type=sa.CHAR(length=36),
        nullable=False,
    )
    op.alter_column(
        "root_cause_suggestions",
        "provider",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.alter_column(
        "root_cause_suggestions",
        "model",
        existing_type=sa.String(length=128),
        nullable=False,
    )
    op.create_unique_constraint("uq_badcase_cluster_grouping", "badcase_clusters", ["grouping_key"])
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
    if _index_exists("root_cause_suggestions", _ROOT_SUGGESTION_CLUSTER_INDEX):
        op.drop_index(_ROOT_SUGGESTION_CLUSTER_INDEX, table_name="root_cause_suggestions")
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


def _backfill_replay_keys() -> None:
    bind = op.get_bind()
    clusters = list(
        bind.execute(
            sa.text(
                "SELECT id, scenario, weakest_dimension, normalized_reason "
                "FROM badcase_clusters ORDER BY created_at, id"
            )
        ).mappings()
    )
    canonical_clusters: dict[str, str] = {}
    for cluster in clusters:
        grouping_key = _grouping_key(
            cluster["scenario"], cluster["weakest_dimension"], cluster["normalized_reason"]
        )
        canonical_id = canonical_clusters.setdefault(grouping_key, cluster["id"])
        if canonical_id != cluster["id"]:
            _merge_legacy_cluster(cluster["id"], canonical_id)
            continue
        bind.execute(
            sa.text("UPDATE badcase_clusters SET grouping_key = :grouping_key WHERE id = :id"),
            {"id": cluster["id"], "grouping_key": grouping_key},
        )

    suggestions = list(
        bind.execute(
            sa.text("SELECT id, cluster_id FROM root_cause_suggestions ORDER BY created_at, id")
        ).mappings()
    )
    seen: set[tuple[str, str, str, str]] = set()
    for suggestion in suggestions:
        provenance = (
            bind.execute(
                sa.text(
                    "SELECT er.id AS evaluation_result_id, runs.provider, runs.model "
                    "FROM cluster_members AS members "
                    "JOIN evaluation_results AS er ON er.id = members.evaluation_result_id "
                    "JOIN evaluation_runs AS runs ON runs.id = er.run_id "
                    "WHERE members.cluster_id = :cluster_id "
                    "ORDER BY members.representative_rank IS NULL, members.representative_rank, "
                    "members.evaluation_result_id LIMIT 1"
                ),
                {"cluster_id": suggestion["cluster_id"]},
            )
            .mappings()
            .first()
        )
        if provenance is None:
            provenance = (
                bind.execute(
                    sa.text(
                        "SELECT er.id AS evaluation_result_id, runs.provider, runs.model "
                        "FROM badcase_clusters AS clusters "
                        "JOIN evaluation_results AS er ON er.run_id = clusters.run_id "
                        "JOIN evaluation_runs AS runs ON runs.id = er.run_id "
                        "WHERE clusters.id = :cluster_id ORDER BY er.created_at, er.id LIMIT 1"
                    ),
                    {"cluster_id": suggestion["cluster_id"]},
                )
                .mappings()
                .first()
            )
        if provenance is None:
            raise RuntimeError(
                "cannot backfill root cause suggestion replay provenance without an evaluation result"
            )
        provider = provenance["provider"] or "legacy-unknown"
        model = provenance["model"] or "legacy-unknown"
        replay_key = (
            suggestion["cluster_id"],
            provider,
            model,
            provenance["evaluation_result_id"],
        )
        if replay_key in seen:
            bind.execute(
                sa.text("DELETE FROM root_cause_suggestions WHERE id = :id"),
                {"id": suggestion["id"]},
            )
            continue
        seen.add(replay_key)
        bind.execute(
            sa.text(
                "UPDATE root_cause_suggestions SET evaluation_result_id = :evaluation_result_id, "
                "provider = :provider, model = :model WHERE id = :id"
            ),
            {
                "id": suggestion["id"],
                "evaluation_result_id": provenance["evaluation_result_id"],
                "provider": provider,
                "model": model,
            },
        )


def _merge_legacy_cluster(cluster_id: str, canonical_id: str) -> None:
    bind = op.get_bind()
    # Preserve every member link and point all existing dependents at the canonical cluster.
    bind.execute(
        sa.text(
            "INSERT IGNORE INTO cluster_members "
            "(cluster_id, evaluation_result_id, representative_rank, confirmed_root_cause, "
            "confirmed_by, confirmed_at) "
            "SELECT :canonical_id, evaluation_result_id, representative_rank, confirmed_root_cause, "
            "confirmed_by, confirmed_at FROM cluster_members WHERE cluster_id = :cluster_id"
        ),
        {"cluster_id": cluster_id, "canonical_id": canonical_id},
    )
    for table in ("root_cause_suggestions", "tasks", "qa_drafts"):
        bind.execute(
            sa.text(
                f"UPDATE {table} SET cluster_id = :canonical_id WHERE cluster_id = :cluster_id"
            ),
            {"cluster_id": cluster_id, "canonical_id": canonical_id},
        )
    bind.execute(
        sa.text("DELETE FROM cluster_members WHERE cluster_id = :cluster_id"),
        {"cluster_id": cluster_id},
    )
    bind.execute(
        sa.text("DELETE FROM badcase_clusters WHERE id = :cluster_id"),
        {"cluster_id": cluster_id},
    )


def _grouping_key(scenario: str | None, weakest_dimension: str, normalized_reason: str) -> str:
    payload = [scenario, weakest_dimension, normalized_reason]
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _index_exists(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    )


def downgrade() -> None:
    op.drop_table("alert_signal_receipts")
    if not _index_exists("root_cause_suggestions", _ROOT_SUGGESTION_CLUSTER_INDEX):
        op.create_index(
            _ROOT_SUGGESTION_CLUSTER_INDEX,
            "root_cause_suggestions",
            ["cluster_id"],
            unique=False,
        )
    op.drop_constraint("fk_root_suggestion_result", "root_cause_suggestions", type_="foreignkey")
    op.drop_constraint("uq_root_suggestion_replay", "root_cause_suggestions", type_="unique")
    op.drop_column("root_cause_suggestions", "model")
    op.drop_column("root_cause_suggestions", "provider")
    op.drop_column("root_cause_suggestions", "evaluation_result_id")
    op.drop_constraint("uq_badcase_cluster_grouping", "badcase_clusters", type_="unique")
    op.drop_column("badcase_clusters", "grouping_key")
