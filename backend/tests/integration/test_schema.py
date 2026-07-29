from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analysis.models import BadcaseCluster
from app.evaluation.models import (
    EvaluationResult,
    EvaluationRun,
    EvaluationTemplate,
    PromptVersion,
    RuleVersion,
)
from app.ingestion.models import Conversation, DataSource
from app.remediation.models import QADraft, QAVersion
from app.shared.audit import AuditEvent, record_audit
from app.shared.enums import (
    AlertStatus,
    Confidence,
    JobStatus,
    QADraftStatus,
    RetestCohort,
    RetestStatus,
    RootCause,
    RunStatus,
    TaskStatus,
    TaskType,
)
from app.shared.types import ImmutableRecordError

EXPECTED_TABLES = {
    "alembic_version",
    "alert_results",
    "alerts",
    "audit_events",
    "badcase_clusters",
    "cluster_members",
    "conversations",
    "data_sources",
    "evaluation_results",
    "evaluation_runs",
    "evaluation_templates",
    "export_records",
    "jobs",
    "model_call_records",
    "prompt_versions",
    "qa_drafts",
    "qa_evidence",
    "qa_export_items",
    "qa_versions",
    "retest_runs",
    "retest_samples",
    "root_cause_suggestions",
    "rule_versions",
    "sampling_batch_conversations",
    "sampling_batches",
    "tasks",
}


@pytest.fixture(scope="module")
def engine():
    database_url = os.environ["TEST_DATABASE_URL"]
    value = create_engine(database_url, pool_pre_ping=True)
    try:
        yield value
    finally:
        value.dispose()


@pytest.fixture
def session(engine) -> Iterator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    value = Session(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield value
    finally:
        value.close()
        transaction.rollback()
        connection.close()


def _evaluation_result(session: Session) -> EvaluationResult:
    suffix = uuid4().hex
    source = DataSource(name=f"source-{suffix}", kind="simulated")
    conversation = Conversation(data_source=source, external_id=f"conversation-{suffix}", body={})
    template = EvaluationTemplate(
        name=f"template-{suffix}",
        version="1",
        weights={"correctness": 1},
        threshold=Decimal("80.00"),
        veto_rules={},
    )
    prompt = PromptVersion(name=f"prompt-{suffix}", version="1", content="Evaluate")
    rule = RuleVersion(kind=f"evaluation-{suffix}", version="1", config={})
    run = EvaluationRun(
        template=template,
        prompt_version=prompt,
        rule_version=rule,
        provider="fake",
        model="fake-v1",
        model_parameters={},
    )
    result = EvaluationResult(
        run=run,
        conversation=conversation,
        total_score=Decimal("90.00"),
        dimension_scores={"correctness": 90},
        passed=True,
        reason="Correct response",
        evidence=["answer"],
        confidence=Confidence.HIGH,
    )
    session.add(result)
    session.commit()
    return result


def test_state_enum_values_are_stable() -> None:
    assert [item.value for item in AlertStatus] == [
        "open",
        "analyzing",
        "awaiting_fix",
        "awaiting_retest",
        "recovered",
        "not_recovered",
        "false_positive",
    ]
    assert [item.value for item in RootCause] == [
        "missing_knowledge",
        "misunderstanding",
        "process_failure",
        "service_tone",
        "other",
    ]
    assert [item.value for item in TaskType] == [
        "attribution_review",
        "qa_review",
        "prompt_optimization",
        "process_investigation",
        "tone_optimization",
        "evaluation_calibration",
        "retest",
    ]
    assert [item.value for item in Confidence] == ["high", "medium", "low"]
    assert [item.value for item in QADraftStatus] == [
        "draft",
        "pending_review",
        "approved",
        "rejected",
        "regeneration_requested",
    ]
    assert [item.value for item in RunStatus] == [
        "queued",
        "running",
        "succeeded",
        "partial",
        "failed",
        "manual_review",
    ]
    assert [item.value for item in TaskStatus] == ["open", "in_progress", "done", "cancelled"]
    assert [item.value for item in JobStatus] == [
        "queued",
        "claimed",
        "succeeded",
        "failed",
        "manual_review",
    ]
    assert [item.value for item in RetestStatus] == [
        "queued",
        "running",
        "recovered",
        "not_recovered",
        "failed",
    ]
    assert [item.value for item in RetestCohort] == ["replay", "new"]


def test_initial_schema_uses_innodb_utf8mb4_and_native_json(engine) -> None:
    with engine.connect() as connection:
        tables = connection.execute(
            text(
                "SELECT TABLE_NAME, ENGINE, TABLE_COLLATION "
                "FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()"
            )
        ).mappings()
        actual = {row["TABLE_NAME"]: row for row in tables}
        json_types = connection.execute(
            text(
                "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND DATA_TYPE = 'json'"
            )
        ).mappings()

    assert set(actual) == EXPECTED_TABLES
    assert {row["ENGINE"] for row in actual.values()} == {"InnoDB"}
    assert all(row["TABLE_COLLATION"].startswith("utf8mb4_") for row in actual.values())
    assert {(row["TABLE_NAME"], row["COLUMN_NAME"]) for row in json_types} >= {
        ("conversations", "body"),
        ("evaluation_results", "dimension_scores"),
        ("jobs", "payload"),
        ("qa_versions", "content"),
    }


def test_conversation_external_id_is_unique_per_source(session: Session) -> None:
    source = DataSource(name=f"demo-{uuid4().hex}", kind="simulated")
    session.add(source)
    session.flush()
    session.add(Conversation(data_source_id=source.id, external_id="c-1", body={}))
    session.commit()
    session.add(Conversation(data_source_id=source.id, external_id="c-1", body={}))

    with pytest.raises(IntegrityError):
        session.commit()


def test_conversation_external_id_can_repeat_across_sources(session: Session) -> None:
    first = DataSource(name=f"first-{uuid4().hex}", kind="simulated")
    second = DataSource(name=f"second-{uuid4().hex}", kind="simulated")
    session.add_all(
        [
            Conversation(data_source=first, external_id="shared", body={}),
            Conversation(data_source=second, external_id="shared", body={}),
        ]
    )

    session.commit()

    assert (
        session.scalar(select(Conversation).where(Conversation.external_id == "shared")) is not None
    )


def test_utc_datetime_normalizes_offsets_and_restores_aware_utc(session: Session) -> None:
    supplied = datetime(2026, 7, 29, 12, 30, 45, 123456, tzinfo=timezone(timedelta(hours=8)))
    source = DataSource(name=f"utc-{uuid4().hex}", kind="simulated", created_at=supplied)
    session.add(source)
    session.commit()
    session.expire(source)

    assert source.created_at == datetime(2026, 7, 29, 4, 30, 45, 123456, tzinfo=UTC)
    assert source.created_at.tzinfo is UTC


def test_evaluation_results_reject_updates_and_deletes(session: Session) -> None:
    result = _evaluation_result(session)
    result.reason = "Changed"

    with pytest.raises(ImmutableRecordError, match="EvaluationResult"):
        session.commit()

    session.rollback()
    result = session.get(EvaluationResult, result.id)
    session.delete(result)

    with pytest.raises(ImmutableRecordError, match="EvaluationResult"):
        session.commit()


def test_qa_versions_are_append_only(session: Session) -> None:
    result = _evaluation_result(session)
    cluster = BadcaseCluster(
        run_id=result.run_id,
        weakest_dimension="correctness",
        normalized_reason="missing policy",
        algorithm_version="v1",
    )
    draft = QADraft(cluster=cluster, confidence=Confidence.HIGH)
    first = QAVersion(
        draft=draft, version_number=1, content={"answer": "v1"}, created_by="operator"
    )
    second = QAVersion(
        draft=draft, version_number=2, content={"answer": "v2"}, created_by="operator"
    )
    session.add_all([first, second])
    session.commit()
    first.content = {"answer": "changed"}

    with pytest.raises(ImmutableRecordError, match="QAVersion"):
        session.commit()

    session.rollback()
    first = session.get(QAVersion, first.id)
    session.delete(first)

    with pytest.raises(ImmutableRecordError, match="QAVersion"):
        session.commit()


def test_record_audit_flushes_without_committing(session: Session) -> None:
    event = record_audit(
        session,
        actor="operator-1",
        action="confirm",
        entity_type="cluster",
        entity_id="cluster-1",
        payload={"root_cause": "missing_knowledge"},
    )

    assert event.id is not None
    assert session.get(AuditEvent, event.id) is event
    session.rollback()
    assert session.get(AuditEvent, event.id) is None


def test_named_constraints_and_claim_indexes_match_contract(engine) -> None:
    inspector = inspect(engine)
    conversation_unique = {
        item["name"] for item in inspector.get_unique_constraints("conversations")
    }
    job_indexes = {item["name"]: item["column_names"] for item in inspector.get_indexes("jobs")}
    alert_indexes = {item["name"]: item["column_names"] for item in inspector.get_indexes("alerts")}

    assert "uq_conversation_source_external" in conversation_unique
    assert job_indexes["ix_job_claim"] == ["status", "run_after", "created_at"]
    assert alert_indexes["ix_alert_status_merge"] == ["status", "merge_key"]


def test_join_tables_reference_the_authoritative_endpoints(engine) -> None:
    inspector = inspect(engine)

    def endpoints(table_name: str) -> set[tuple[str, str, str]]:
        return {
            (
                foreign_key["constrained_columns"][0],
                foreign_key["referred_table"],
                foreign_key["referred_columns"][0],
            )
            for foreign_key in inspector.get_foreign_keys(table_name)
        }

    assert endpoints("cluster_members") == {
        ("cluster_id", "badcase_clusters", "id"),
        ("evaluation_result_id", "evaluation_results", "id"),
    }
    assert endpoints("alert_results") == {
        ("alert_id", "alerts", "id"),
        ("evaluation_result_id", "evaluation_results", "id"),
    }
    assert endpoints("qa_evidence") == {
        ("qa_version_id", "qa_versions", "id"),
        ("conversation_id", "conversations", "id"),
        ("evaluation_result_id", "evaluation_results", "id"),
    }
    assert endpoints("retest_samples") == {
        ("retest_run_id", "retest_runs", "id"),
        ("conversation_id", "conversations", "id"),
        ("source_evaluation_result_id", "evaluation_results", "id"),
        ("retest_evaluation_result_id", "evaluation_results", "id"),
    }
