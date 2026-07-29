from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from alembic import command
from app.config import settings

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@contextmanager
def _temporary_mysql_database(database_url: str) -> Iterator[str]:
    source_url = make_url(database_url)
    database_name = f"task7_migration_{uuid4().hex}"
    admin_engine = create_engine(source_url.set(database=None), isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f"CREATE DATABASE `{database_name}` CHARACTER SET utf8mb4"))
        yield source_url.set(database=database_name).render_as_string(hide_password=False)
    finally:
        with admin_engine.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS `{database_name}`"))
        admin_engine.dispose()


def _seed_dirty_0002(engine) -> dict[str, str]:
    ids = {
        name: str(uuid4())
        for name in (
            "template",
            "prompt",
            "rule",
            "run",
            "cluster",
            "task_canonical",
            "task_duplicate",
            "draft_canonical",
            "draft_duplicate",
            "version_canonical",
            "version_duplicate",
            "evidence",
            "export_canonical",
            "export_duplicate",
            "alert",
            "retest",
            "audit_task",
            "audit_draft",
            "audit_export",
        )
    }
    created_at = datetime(2026, 7, 30, tzinfo=UTC)
    later = created_at + timedelta(seconds=1)
    content = json.dumps(
        {
            "question": "退款何时到账？",
            "answer": "一个工作日",
            "applicability": "退款",
            "handling_steps": ["核实状态"],
            "estimated_time": "一个工作日",
            "escalation": "转人工",
        },
        ensure_ascii=False,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO evaluation_templates "
                "(id, name, version, weights, threshold, veto_rules, active, created_at) "
                "VALUES (:id, :name, '1', :weights, 80, :rules, 1, :created_at)"
            ),
            {
                "id": ids["template"],
                "name": f"task7-template-{ids['template']}",
                "weights": json.dumps({"correctness": 1}),
                "rules": json.dumps({}),
                "created_at": created_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO prompt_versions (id, name, version, content, active, created_at) "
                "VALUES (:id, :name, '1', 'Evaluate', 1, :created_at)"
            ),
            {
                "id": ids["prompt"],
                "name": f"task7-prompt-{ids['prompt']}",
                "created_at": created_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO rule_versions (id, kind, version, config, active, created_at) "
                "VALUES (:id, :kind, '1', :config, 1, :created_at)"
            ),
            {
                "id": ids["rule"],
                "kind": f"task7-rule-{ids['rule']}",
                "config": json.dumps({}),
                "created_at": created_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO evaluation_runs "
                "(id, sampling_batch_id, template_id, prompt_version_id, rule_version_id, provider, "
                "model, model_parameters, status, succeeded_count, failed_count, created_at, "
                "started_at, completed_at) VALUES (:id, NULL, :template, :prompt, :rule, 'test', "
                "'test-v1', :parameters, 'succeeded', 0, 0, :created_at, NULL, :created_at)"
            ),
            {
                "id": ids["run"],
                "template": ids["template"],
                "prompt": ids["prompt"],
                "rule": ids["rule"],
                "parameters": json.dumps({}),
                "created_at": created_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO badcase_clusters "
                "(id, run_id, scenario, weakest_dimension, normalized_reason, algorithm_version, "
                "grouping_key, created_at) VALUES (:id, :run, 'refund', 'correctness', 'refund', "
                "'v1', :grouping_key, :created_at)"
            ),
            {
                "id": ids["cluster"],
                "run": ids["run"],
                "grouping_key": uuid4().hex,
                "created_at": created_at,
            },
        )
        for key, row_created_at in (
            ("task_canonical", created_at),
            ("task_duplicate", later),
        ):
            connection.execute(
                text(
                    "INSERT INTO tasks "
                    "(id, type, status, alert_id, cluster_id, title, priority, payload, created_at, "
                    "updated_at, completed_at) VALUES (:id, 'qa_review', 'open', NULL, :cluster, "
                    "'QA review', 'P2', :payload, :created_at, :created_at, NULL)"
                ),
                {
                    "id": ids[key],
                    "cluster": ids["cluster"],
                    "payload": json.dumps({}),
                    "created_at": row_created_at,
                },
            )
        for draft_key, task_key, row_created_at in (
            ("draft_canonical", "task_canonical", created_at),
            ("draft_duplicate", "task_duplicate", later),
        ):
            connection.execute(
                text(
                    "INSERT INTO qa_drafts "
                    "(id, cluster_id, task_id, status, current_version_number, confidence, "
                    "created_at, updated_at) VALUES (:id, :cluster, :task, 'approved', 1, 'high', "
                    ":created_at, :created_at)"
                ),
                {
                    "id": ids[draft_key],
                    "cluster": ids["cluster"],
                    "task": ids[task_key],
                    "created_at": row_created_at,
                },
            )
        for version_key, draft_key, actor, row_created_at in (
            ("version_canonical", "draft_canonical", "operator-a", created_at),
            ("version_duplicate", "draft_duplicate", "operator-b", later),
        ):
            connection.execute(
                text(
                    "INSERT INTO qa_versions "
                    "(id, draft_id, version_number, content, created_by, approved_by, approved_at, "
                    "created_at) VALUES (:id, :draft, 1, :content, :actor, :actor, :created_at, "
                    ":created_at)"
                ),
                {
                    "id": ids[version_key],
                    "draft": ids[draft_key],
                    "content": content,
                    "actor": actor,
                    "created_at": row_created_at,
                },
            )
        connection.execute(
            text(
                "INSERT INTO qa_evidence "
                "(id, qa_version_id, source_type, source_ref, excerpt, conversation_id, "
                "evaluation_result_id, created_at) VALUES (:id, :version, 'business_reference', "
                "'policy/refund', '一个工作日', NULL, NULL, :created_at)"
            ),
            {
                "id": ids["evidence"],
                "version": ids["version_duplicate"],
                "created_at": later,
            },
        )
        for export_key, actor, row_created_at in (
            ("export_canonical", "operator-a", created_at),
            ("export_duplicate", "operator-b", later),
        ):
            connection.execute(
                text(
                    "INSERT INTO export_records "
                    "(id, format, created_by, artifact_path, artifact_hash, status, created_at) "
                    "VALUES (:id, 'csv', :actor, :path, 'same-hash', 'ready', :created_at)"
                ),
                {
                    "id": ids[export_key],
                    "actor": actor,
                    "path": f"qa-exports/{export_key}.csv",
                    "created_at": row_created_at,
                },
            )
        connection.execute(
            text(
                "INSERT INTO qa_export_items (export_id, qa_version_id) VALUES "
                "(:canonical_export, :canonical_version), (:duplicate_export, :duplicate_version)"
            ),
            {
                "canonical_export": ids["export_canonical"],
                "canonical_version": ids["version_canonical"],
                "duplicate_export": ids["export_duplicate"],
                "duplicate_version": ids["version_duplicate"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO alerts "
                "(id, kind, priority, scenario, root_cause, status, merge_key, baseline_value, "
                "current_value, impact_count, window_started_at, window_ended_at, created_at, "
                "updated_at) VALUES (:id, 'score_drop', 'P2', 'refund', NULL, 'open', :merge_key, "
                "0.9, 0.5, 1, :created_at, :created_at, :created_at, :created_at)"
            ),
            {
                "id": ids["alert"],
                "merge_key": f"task7-{ids['alert']}",
                "created_at": created_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO retest_runs "
                "(id, alert_id, qa_version_id, rule_version_id, status, before_pass_rate, "
                "replay_pass_rate, new_sample_pass_rate, created_at, started_at, completed_at) "
                "VALUES (:id, :alert, :version, :rule, 'queued', NULL, NULL, NULL, :created_at, "
                "NULL, NULL)"
            ),
            {
                "id": ids["retest"],
                "alert": ids["alert"],
                "version": ids["version_duplicate"],
                "rule": ids["rule"],
                "created_at": later,
            },
        )
        for audit_key, entity_type, entity_key in (
            ("audit_task", "task", "task_duplicate"),
            ("audit_draft", "qa_draft", "draft_duplicate"),
            ("audit_export", "export_record", "export_duplicate"),
        ):
            connection.execute(
                text(
                    "INSERT INTO audit_events "
                    "(id, actor, action, entity_type, entity_id, payload, created_at) "
                    "VALUES (:id, 'operator-b', 'legacy', :entity_type, :entity_id, :payload, "
                    ":created_at)"
                ),
                {
                    "id": ids[audit_key],
                    "entity_type": entity_type,
                    "entity_id": ids[entity_key],
                    "payload": json.dumps({}),
                    "created_at": later,
                },
            )
    return ids


def test_0003_deduplicates_dirty_0002_before_constraints_and_survives_downgrade() -> None:
    shared_database_url = os.environ["TEST_DATABASE_URL"]
    if make_url(shared_database_url).get_backend_name() != "mysql":
        pytest.skip("dirty migration verification requires disposable MySQL database privileges")
    original_url = settings.database_url
    with _temporary_mysql_database(shared_database_url) as database_url:
        engine = create_engine(database_url, pool_pre_ping=True)
        config = _alembic_config(database_url)
        settings.database_url = database_url
        try:
            command.upgrade(config, "0002")
            engine.dispose()
            ids = _seed_dirty_0002(engine)

            command.upgrade(config, "0003")
            engine.dispose()

            with engine.connect() as connection:
                assert connection.execute(
                    text("SELECT id FROM tasks WHERE cluster_id = :cluster"),
                    {"cluster": ids["cluster"]},
                ).scalars().all() == [ids["task_canonical"]]
                draft = (
                    connection.execute(
                        text(
                            "SELECT id, task_id, current_version_number FROM qa_drafts "
                            "WHERE task_id = :task"
                        ),
                        {"task": ids["task_canonical"]},
                    )
                    .mappings()
                    .one()
                )
                assert dict(draft) == {
                    "id": ids["draft_canonical"],
                    "task_id": ids["task_canonical"],
                    "current_version_number": 2,
                }
                versions = (
                    connection.execute(
                        text(
                            "SELECT id, draft_id, version_number FROM qa_versions "
                            "WHERE draft_id = :draft ORDER BY version_number"
                        ),
                        {"draft": ids["draft_canonical"]},
                    )
                    .mappings()
                    .all()
                )
                assert [dict(row) for row in versions] == [
                    {
                        "id": ids["version_canonical"],
                        "draft_id": ids["draft_canonical"],
                        "version_number": 1,
                    },
                    {
                        "id": ids["version_duplicate"],
                        "draft_id": ids["draft_canonical"],
                        "version_number": 2,
                    },
                ]
                assert (
                    connection.execute(
                        text("SELECT qa_version_id FROM qa_evidence WHERE id = :id"),
                        {"id": ids["evidence"]},
                    ).scalar_one()
                    == ids["version_duplicate"]
                )
                assert (
                    connection.execute(
                        text("SELECT qa_version_id FROM retest_runs WHERE id = :id"),
                        {"id": ids["retest"]},
                    ).scalar_one()
                    == ids["version_duplicate"]
                )
                assert connection.execute(
                    text(
                        "SELECT id, created_by FROM export_records WHERE artifact_hash = 'same-hash'"
                    )
                ).one() == (ids["export_canonical"], "operator-a")
                assert set(
                    connection.execute(
                        text("SELECT qa_version_id FROM qa_export_items WHERE export_id = :id"),
                        {"id": ids["export_canonical"]},
                    ).scalars()
                ) == {ids["version_canonical"], ids["version_duplicate"]}
                audit_targets = connection.execute(
                    text("SELECT entity_type, entity_id FROM audit_events WHERE action = 'legacy'")
                ).all()
                assert set(audit_targets) == {
                    ("task", ids["task_canonical"]),
                    ("qa_draft", ids["draft_canonical"]),
                    ("export_record", ids["export_canonical"]),
                }

            uniques = {
                table: {item["name"] for item in inspect(engine).get_unique_constraints(table)}
                for table in ("tasks", "qa_drafts", "export_records")
            }
            assert "uq_task_cluster_type" in uniques["tasks"]
            assert "uq_qa_draft_task" in uniques["qa_drafts"]
            assert "uq_export_record_format_hash" in uniques["export_records"]

            command.downgrade(config, "0002")
            engine.dispose()
            assert "ix_task_cluster_id" in {
                item["name"] for item in inspect(engine).get_indexes("tasks")
            }
            assert "ix_qa_draft_task_id" in {
                item["name"] for item in inspect(engine).get_indexes("qa_drafts")
            }
            command.upgrade(config, "0003")
        finally:
            engine.dispose()
            settings.database_url = original_url
