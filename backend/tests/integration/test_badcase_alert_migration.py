from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.analysis.models import BadcaseCluster, ClusterMember, RootCauseSuggestion
from app.analysis.service import (
    GROUPING_ALGORITHM_VERSION,
    ClusterDraft,
    attribute_cluster,
    persist_clusters,
)
from app.config import settings
from app.evaluation.contracts import AttributionRequest, ProviderAttribution
from app.evaluation.providers import EvaluationProvider, ProviderIdentity

BACKEND_DIR = Path(__file__).resolve().parents[2]


class LegacyAttributionTransport:
    identity = ProviderIdentity(provider="legacy-provider", model="legacy-model")

    def evaluate(self, request: object) -> object:
        raise AssertionError("evaluation is not expected during legacy attribution replay")

    def attribute(self, request: AttributionRequest) -> ProviderAttribution:
        raise AssertionError("a migrated legacy suggestion should be replayed without attribution")

    def draft_qa(self, request: object) -> object:
        raise AssertionError("QA drafting is not expected during legacy attribution replay")


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@contextmanager
def _temporary_mysql_database(database_url: str) -> Iterator[str]:
    source_url = make_url(database_url)
    database_name = f"task6_migration_{uuid4().hex}"
    admin_engine = create_engine(source_url.set(database=None), isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f"CREATE DATABASE `{database_name}` CHARACTER SET utf8mb4"))
        yield source_url.set(database=database_name).render_as_string(hide_password=False)
    finally:
        with admin_engine.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS `{database_name}`"))
        admin_engine.dispose()


def _seed_0001_legacy_rows(engine) -> dict[str, str]:
    identifiers = {
        "source": str(uuid4()),
        "conversation": str(uuid4()),
        "template": str(uuid4()),
        "prompt": str(uuid4()),
        "rule": str(uuid4()),
        "run": str(uuid4()),
        "result": str(uuid4()),
        "cluster": str(uuid4()),
        "suggestion": str(uuid4()),
    }
    created_at = datetime(2026, 7, 30, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO data_sources "
                "(id, name, kind, config, enabled, created_at, updated_at) "
                "VALUES (:id, :name, 'simulated', :config, 1, :created_at, :created_at)"
            ),
            {
                "id": identifiers["source"],
                "name": f"legacy-source-{identifiers['source']}",
                "config": json.dumps({}),
                "created_at": created_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO conversations "
                "(id, data_source_id, external_id, scenario, status, body, occurred_at, created_at) "
                "VALUES (:id, :source_id, 'legacy-conversation', 'refund', NULL, :body, "
                ":created_at, :created_at)"
            ),
            {
                "id": identifiers["conversation"],
                "source_id": identifiers["source"],
                "body": json.dumps({"messages": []}),
                "created_at": created_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO evaluation_templates "
                "(id, name, version, weights, threshold, veto_rules, active, created_at) "
                "VALUES (:id, :name, '1', :weights, 80.00, :veto_rules, 1, :created_at)"
            ),
            {
                "id": identifiers["template"],
                "name": f"legacy-template-{identifiers['template']}",
                "weights": json.dumps({"correctness": 1}),
                "veto_rules": json.dumps({}),
                "created_at": created_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO prompt_versions (id, name, version, content, active, created_at) "
                "VALUES (:id, :name, '1', 'Evaluate', 1, :created_at)"
            ),
            {
                "id": identifiers["prompt"],
                "name": f"legacy-prompt-{identifiers['prompt']}",
                "created_at": created_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO rule_versions (id, kind, version, config, active, created_at) "
                "VALUES (:id, :kind, '1', :config, 1, :created_at)"
            ),
            {
                "id": identifiers["rule"],
                "kind": f"legacy-rule-{identifiers['rule']}",
                "config": json.dumps({}),
                "created_at": created_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO evaluation_runs "
                "(id, sampling_batch_id, template_id, prompt_version_id, rule_version_id, provider, model, "
                "model_parameters, status, succeeded_count, failed_count, created_at, started_at, completed_at) "
                "VALUES (:id, NULL, :template_id, :prompt_id, :rule_id, 'legacy-provider', "
                "'legacy-model', :parameters, 'succeeded', 0, 1, :created_at, NULL, :created_at)"
            ),
            {
                "id": identifiers["run"],
                "template_id": identifiers["template"],
                "prompt_id": identifiers["prompt"],
                "rule_id": identifiers["rule"],
                "parameters": json.dumps({}),
                "created_at": created_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO evaluation_results "
                "(id, run_id, conversation_id, total_score, dimension_scores, passed, reason, evidence, "
                "confidence, severe_factual_error, severe_compliance_error, created_at) "
                "VALUES (:id, :run_id, :conversation_id, 40.00, :dimensions, 0, "
                "'Missing refund policy details!', :evidence, 'high', 0, 0, :created_at)"
            ),
            {
                "id": identifiers["result"],
                "run_id": identifiers["run"],
                "conversation_id": identifiers["conversation"],
                "dimensions": json.dumps(
                    {
                        "correctness": 20,
                        "completeness": 60,
                        "relevance": 70,
                        "service_experience": 80,
                        "compliance": 90,
                    }
                ),
                "evidence": json.dumps(["Refund policy requires manager approval."]),
                "created_at": created_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO badcase_clusters "
                "(id, run_id, scenario, weakest_dimension, normalized_reason, algorithm_version, created_at) "
                "VALUES (:id, :run_id, 'refund', 'correctness', 'missing refund policy details', "
                "'badcase-grouping-v1', :created_at)"
            ),
            {
                "id": identifiers["cluster"],
                "run_id": identifiers["run"],
                "created_at": created_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO cluster_members "
                "(cluster_id, evaluation_result_id, representative_rank, confirmed_root_cause, confirmed_by, "
                "confirmed_at) VALUES (:cluster_id, :result_id, 1, NULL, NULL, NULL)"
            ),
            {"cluster_id": identifiers["cluster"], "result_id": identifiers["result"]},
        )
        connection.execute(
            text(
                "INSERT INTO root_cause_suggestions "
                "(id, cluster_id, root_cause, reason, evidence, confidence, created_at) "
                "VALUES (:id, :cluster_id, 'missing_knowledge', 'Legacy reason', :evidence, 'high', "
                ":created_at)"
            ),
            {
                "id": identifiers["suggestion"],
                "cluster_id": identifiers["cluster"],
                "evidence": json.dumps(["Refund policy requires manager approval."]),
                "created_at": created_at,
            },
        )
    return identifiers


def test_0002_backfills_legacy_replay_keys_and_enforces_them() -> None:
    shared_database_url = os.environ["TEST_DATABASE_URL"]
    original_url = settings.database_url
    with _temporary_mysql_database(shared_database_url) as database_url:
        engine = create_engine(database_url, pool_pre_ping=True)
        config = _alembic_config(database_url)
        settings.database_url = database_url
        try:
            command.upgrade(config, "0001")
            engine.dispose()
            identifiers = _seed_0001_legacy_rows(engine)

            command.upgrade(config, "0002")
            engine.dispose()

            inspector = inspect(engine)
            cluster_columns = {
                column["name"]: column for column in inspector.get_columns("badcase_clusters")
            }
            suggestion_columns = {
                column["name"]: column for column in inspector.get_columns("root_cause_suggestions")
            }
            assert cluster_columns["grouping_key"]["nullable"] is False
            assert suggestion_columns["evaluation_result_id"]["nullable"] is False
            assert suggestion_columns["provider"]["nullable"] is False
            assert suggestion_columns["model"]["nullable"] is False

            with Session(engine, expire_on_commit=False) as session:
                cluster = session.get(BadcaseCluster, identifiers["cluster"])
                suggestion = session.get(RootCauseSuggestion, identifiers["suggestion"])
                assert cluster is not None
                assert suggestion is not None
                assert cluster.grouping_key
                assert suggestion.evaluation_result_id == identifiers["result"]
                assert (suggestion.provider, suggestion.model) == (
                    "legacy-provider",
                    "legacy-model",
                )

                replay = persist_clusters(
                    session,
                    [
                        ClusterDraft(
                            run_id=identifiers["run"],
                            scenario="refund",
                            weakest_dimension="correctness",
                            normalized_reason="missing refund policy details",
                            algorithm_version=GROUPING_ALGORITHM_VERSION,
                            member_ids=(identifiers["result"],),
                            representative_ids=(identifiers["result"],),
                        )
                    ],
                )
                assert replay[0].id == identifiers["cluster"]
                assert (
                    attribute_cluster(
                        session,
                        identifiers["cluster"],
                        EvaluationProvider(LegacyAttributionTransport()),
                    ).id
                    == identifiers["suggestion"]
                )
                assert len(session.scalars(select(ClusterMember)).all()) == 1

                with pytest.raises(IntegrityError):
                    session.execute(
                        text("UPDATE badcase_clusters SET grouping_key = NULL WHERE id = :id"),
                        {"id": identifiers["cluster"]},
                    )
                session.rollback()
                with pytest.raises(IntegrityError):
                    session.execute(
                        text("UPDATE root_cause_suggestions SET provider = NULL WHERE id = :id"),
                        {"id": identifiers["suggestion"]},
                    )
                session.rollback()

            command.downgrade(config, "0001")
            engine.dispose()
            assert "grouping_key" not in {
                column["name"] for column in inspect(engine).get_columns("badcase_clusters")
            }
            command.upgrade(config, "head")
        finally:
            engine.dispose()
            settings.database_url = original_url
