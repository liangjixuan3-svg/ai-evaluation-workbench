from __future__ import annotations

import csv
import io
import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.alerts.models import Task
from app.analysis.models import BadcaseCluster
from app.evaluation.models import EvaluationRun, EvaluationTemplate, PromptVersion, RuleVersion
from app.ingestion.models import DataSource
from app.remediation.export import InvalidQAState, QAExportDocument, export_qa
from app.remediation.models import ExportRecord, QADraft, QAVersion
from app.remediation.service import MissingBusinessEvidence, approve_qa
from app.shared.audit import AuditEvent
from app.shared.enums import Confidence, QADraftStatus, TaskType


@pytest.fixture(scope="module")
def engine():
    value = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
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


@pytest.fixture
def business_evidence() -> dict[str, str]:
    return {"source_ref": "policy/refund-v3", "excerpt": "退款需在一个工作日内完成审核。"}


@pytest.fixture
def draft(session: Session) -> QADraft:
    return _create_draft(session)


def _create_draft(session: Session) -> QADraft:
    suffix = uuid4().hex
    source = DataSource(name=f"qa-source-{suffix}", kind="test")
    template = EvaluationTemplate(
        name=f"qa-template-{suffix}",
        version="1",
        weights={"correctness": 1},
        threshold=Decimal(80),
        veto_rules={},
    )
    prompt = PromptVersion(name=f"qa-prompt-{suffix}", version="1", content="test")
    rule = RuleVersion(kind=f"qa-rule-{suffix}", version="1", config={})
    run = EvaluationRun(
        template=template,
        prompt_version=prompt,
        rule_version=rule,
        provider="test",
        model="test-v1",
        model_parameters={},
    )
    session.add_all((source, run))
    session.flush()
    cluster = BadcaseCluster(
        run_id=run.id,
        weakest_dimension="correctness",
        normalized_reason="refund policy",
        algorithm_version="v1",
        grouping_key=f"qa-cluster-{suffix}",
    )
    session.add(cluster)
    session.flush()
    task = Task(
        type=TaskType.QA_REVIEW,
        cluster_id=cluster.id,
        title="QA review",
        priority="P2",
        payload={},
    )
    session.add(task)
    session.flush()
    draft = QADraft(
        cluster_id=cluster.id,
        task_id=task.id,
        status=QADraftStatus.PENDING_REVIEW,
        current_version_number=1,
        confidence=Confidence.HIGH,
    )
    version = QAVersion(
        draft=draft,
        version_number=1,
        content={
            "question": "退款何时到账？",
            "answer": "初始答案",
            "applicability": "退款场景",
            "handling_steps": ["核实退款状态"],
            "estimated_time": "1 个工作日",
            "escalation": "规则不明确时转人工",
        },
        created_by="provider:test-v1",
    )
    session.add_all((draft, version))
    session.commit()
    return draft


def test_qa_without_business_evidence_cannot_be_approved(session, draft) -> None:
    with pytest.raises(MissingBusinessEvidence):
        approve_qa(session, draft.id, actor="operator-1", edits=None)


def test_malformed_business_evidence_does_not_append_version(session, draft) -> None:
    with pytest.raises(MissingBusinessEvidence):
        approve_qa(
            session,
            draft.id,
            actor="operator-1",
            edits={"business_evidence": [{"source_ref": "policy/refund-v3"}]},
        )

    versions = session.scalars(select(QAVersion).where(QAVersion.draft_id == draft.id)).all()
    assert len(versions) == 1
    assert draft.status == QADraftStatus.PENDING_REVIEW


def test_approval_appends_an_immutable_version(session, draft, business_evidence) -> None:
    original = draft.current_version

    approved = approve_qa(
        session,
        draft.id,
        actor="operator-1",
        edits={"answer": "编辑后的答案", "business_evidence": [business_evidence]},
    )

    assert approved.version_number == original.version_number + 1
    assert original.content["answer"] == "初始答案"
    assert approved.content["answer"] == "编辑后的答案"
    assert approved.approved_by == "operator-1"


def test_approval_locks_draft_before_reading_current_version(
    session, draft, business_evidence
) -> None:
    draft_id = draft.id
    session.expunge_all()
    draft_select_locks: list[bool] = []

    def capture_draft_select(execute_state) -> None:
        if not execute_state.is_select:
            return
        if any(
            description.get("entity") is QADraft
            for description in execute_state.statement.column_descriptions
        ):
            draft_select_locks.append(execute_state.statement._for_update_arg is not None)

    event.listen(session, "do_orm_execute", capture_draft_select)
    try:
        approve_qa(
            session,
            draft_id,
            actor="operator-1",
            edits={"business_evidence": [business_evidence]},
        )
    finally:
        event.remove(session, "do_orm_execute", capture_draft_select)

    assert draft_select_locks[0] is True


def test_concurrent_approvals_serialize_across_two_sessions(engine, business_evidence) -> None:
    if engine.dialect.name != "mysql":
        pytest.skip("row-lock concurrency semantics require MySQL/InnoDB")
    with Session(engine, expire_on_commit=False) as seed_session:
        draft_id = _create_draft(seed_session).id
    barrier = Barrier(2)

    def approve(actor: str, answer: str) -> int:
        with Session(engine, expire_on_commit=False) as worker_session:
            barrier.wait()
            return approve_qa(
                worker_session,
                draft_id,
                actor=actor,
                edits={
                    "answer": answer,
                    "business_evidence": [business_evidence],
                },
            ).version_number

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(approve, "operator-a", "并发答案 A"),
            executor.submit(approve, "operator-b", "并发答案 B"),
        ]
        version_numbers = sorted(future.result(timeout=10) for future in futures)

    assert version_numbers == [2, 3]
    with Session(engine) as verification_session:
        draft = verification_session.get(QADraft, draft_id)
        assert draft is not None
        assert draft.current_version_number == 3


def test_only_approved_version_can_be_exported(session, draft) -> None:
    with pytest.raises(InvalidQAState):
        export_qa(session, [draft.id], "csv")


def test_export_is_deterministic_utf8_csv_and_strict_json(
    session, draft, business_evidence
) -> None:
    approve_qa(
        session,
        draft.id,
        actor="operator-1",
        edits={"business_evidence": [business_evidence]},
    )

    csv_artifact = export_qa(session, [draft.id], "csv", actor="operator-1")
    replay = export_qa(session, [draft.id], "csv", actor="operator-1")
    rows = list(csv.reader(io.StringIO(csv_artifact.content.decode("utf-8"))))
    json_artifact = export_qa(session, [draft.id], "json", actor="operator-1")
    document = QAExportDocument.model_validate(json.loads(json_artifact.content))

    assert rows[0] == [
        "draft_id",
        "version_number",
        "question",
        "answer",
        "applicability",
        "handling_steps",
        "estimated_time",
        "escalation",
    ]
    assert csv_artifact.metadata == replay.metadata
    assert csv_artifact.content == replay.content
    assert document.items[0].answer == "初始答案"


def test_every_export_invocation_records_actor_without_mutating_artifact_provenance(
    session, draft, business_evidence
) -> None:
    approve_qa(
        session,
        draft.id,
        actor="operator-1",
        edits={"business_evidence": [business_evidence]},
    )

    first = export_qa(session, [draft.id], "csv", actor="operator-1")
    provenance = (
        first.record.created_by,
        first.record.artifact_path,
        first.record.artifact_hash,
        first.record.created_at,
    )
    replay = export_qa(session, [draft.id], "csv", actor="operator-2")

    assert replay.record.id == first.record.id
    assert (
        replay.record.created_by,
        replay.record.artifact_path,
        replay.record.artifact_hash,
        replay.record.created_at,
    ) == provenance
    assert session.scalars(
        select(ExportRecord).where(
            ExportRecord.format == first.record.format,
            ExportRecord.artifact_hash == first.record.artifact_hash,
        )
    ).all() == [first.record]
    events = session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.action == "qa_exported",
            AuditEvent.entity_id == first.record.id,
        )
        .order_by(AuditEvent.created_at, AuditEvent.id)
    ).all()
    assert [item.actor for item in events] == ["operator-1", "operator-2"]


def test_0003_downgrade_preserves_indexes_required_by_foreign_keys(monkeypatch) -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    migration = script.get_revision("0003").module
    calls: list[tuple[str, str]] = []

    class RecordingOperations:
        def create_index(self, name, table_name, columns, unique) -> None:
            calls.append(("create_index", name))

        def drop_constraint(self, name, table_name, type_) -> None:
            calls.append(("drop_constraint", name))

    monkeypatch.setattr(migration, "op", RecordingOperations())
    monkeypatch.setattr(
        migration, "_index_exists", lambda table_name, index_name: False, raising=False
    )

    migration.downgrade()

    assert calls == [
        ("create_index", "ix_task_cluster_id"),
        ("create_index", "ix_qa_draft_task_id"),
        ("drop_constraint", "uq_export_record_format_hash"),
        ("drop_constraint", "uq_qa_draft_task"),
        ("drop_constraint", "uq_task_cluster_type"),
    ]


def test_0003_upgrade_removes_downgrade_only_indexes(monkeypatch) -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    migration = script.get_revision("0003").module
    calls: list[tuple[str, str]] = []

    class RecordingOperations:
        def create_unique_constraint(self, name, table_name, columns) -> None:
            calls.append(("create_unique_constraint", name))

        def drop_index(self, name, table_name) -> None:
            calls.append(("drop_index", name))

    monkeypatch.setattr(migration, "op", RecordingOperations())
    monkeypatch.setattr(
        migration,
        "_deduplicate_legacy_rows",
        lambda: calls.append(("preflight", "legacy_rows")),
        raising=False,
    )
    monkeypatch.setattr(
        migration, "_index_exists", lambda table_name, index_name: True, raising=False
    )

    migration.upgrade()

    assert calls == [
        ("preflight", "legacy_rows"),
        ("create_unique_constraint", "uq_task_cluster_type"),
        ("create_unique_constraint", "uq_qa_draft_task"),
        ("create_unique_constraint", "uq_export_record_format_hash"),
        ("drop_index", "ix_task_cluster_id"),
        ("drop_index", "ix_qa_draft_task_id"),
    ]
