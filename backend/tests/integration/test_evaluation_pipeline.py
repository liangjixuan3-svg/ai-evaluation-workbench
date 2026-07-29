from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.evaluation.contracts import EvaluationRequest, ProviderEvaluation
from app.evaluation.models import (
    EvaluationResult,
    EvaluationRun,
    EvaluationTemplate,
    ModelCallRecord,
    PromptVersion,
    RuleVersion,
)
from app.evaluation.providers import EvaluationProvider
from app.evaluation.service import run_evaluation_batch
from app.ingestion.models import (
    Conversation,
    DataSource,
    SamplingBatch,
    SamplingBatchConversation,
)
from app.jobs.models import Job
from app.jobs.repository import enqueue_job
from app.main import create_app
from app.shared.enums import JobStatus, RunStatus
from app.shared.types import utc_now


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


class FlakyTransport:
    def __init__(self, failures: set[str] | None = None) -> None:
        self.failures = failures or set()
        self.requests: list[EvaluationRequest] = []

    def evaluate(self, request: EvaluationRequest) -> ProviderEvaluation:
        self.requests.append(request)
        if request.conversation.external_id in self.failures:
            raise RuntimeError(f"provider failure for {request.conversation.external_id}")
        evidence = request.conversation.messages[0].content
        return ProviderEvaluation(
            dimensions={
                "correctness": 90,
                "completeness": 90,
                "relevance": 90,
                "service_experience": 90,
                "compliance": 90,
            },
            reason="The response is complete and compliant.",
            evidence=[evidence],
            confidence=0.9,
        )


def _run_with_sample(session: Session, count: int = 3) -> tuple[EvaluationRun, list[Conversation]]:
    suffix = uuid4().hex
    source = DataSource(name=f"pipeline-{suffix}", kind="simulated")
    conversations = [
        Conversation(
            data_source=source,
            external_id=f"conversation-{index}-{suffix}",
            scenario="refund_progress",
            status="closed",
            occurred_at=datetime(2026, 7, 30, tzinfo=UTC),
            body={
                "messages": [
                    {
                        "role": "assistant",
                        "content": (
                            f"请联系 13800138000 查询订单 ORD-20260730-AB{index:02d} 的退款进度。"
                        ),
                    }
                ]
            },
        )
        for index in range(count)
    ]
    batch = SamplingBatch(policy_version=f"sample-{suffix}", seed=7, selected_count=count)
    template = EvaluationTemplate(
        name=f"template-{suffix}",
        version="template-v3",
        weights={
            "correctness": 0.2,
            "completeness": 0.2,
            "relevance": 0.2,
            "service_experience": 0.2,
            "compliance": 0.2,
        },
        threshold=Decimal("80.00"),
        veto_rules={"severe_errors": "fail"},
    )
    prompt = PromptVersion(name=f"prompt-{suffix}", version="prompt-v4", content="Evaluate")
    rule = RuleVersion(kind=f"evaluation-{suffix}", version="rules-v5", config={})
    run = EvaluationRun(
        sampling_batch=batch,
        template=template,
        prompt_version=prompt,
        rule_version=rule,
        provider="public-test-provider",
        model="model-v9",
        model_parameters={"temperature": 0},
    )
    session.add_all([run, *conversations])
    session.flush()
    session.add_all(
        [
            SamplingBatchConversation(
                batch_id=batch.id,
                conversation_id=conversation.id,
                selection_reason="random",
            )
            for conversation in conversations
        ]
    )
    session.commit()
    return run, conversations


def test_batch_keeps_success_when_one_item_fails(session: Session) -> None:
    run, conversations = _run_with_sample(session)
    failed = conversations[-1]
    transport = FlakyTransport({failed.external_id})

    summary = run_evaluation_batch(session, run.id, EvaluationProvider(transport))
    stored_run = session.get(EvaluationRun, run.id)

    assert summary.succeeded == 2
    assert summary.failed == 1
    assert stored_run is not None
    assert stored_run.status == RunStatus.PARTIAL
    assert (
        len(
            list(session.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run.id)))
        )
        == 2
    )
    assert all(
        "13800138000" not in request.conversation.messages[0].content
        for request in transport.requests
    )
    assert all(
        "[PHONE]" in request.conversation.messages[0].content for request in transport.requests
    )


def test_rerun_resumes_only_the_failed_item_without_duplicate_results(session: Session) -> None:
    run, conversations = _run_with_sample(session)
    failed = conversations[-1]
    transport = FlakyTransport({failed.external_id})
    provider = EvaluationProvider(transport)

    first = run_evaluation_batch(session, run.id, provider)
    retry = session.scalar(
        select(Job).where(Job.idempotency_key == f"evaluation-item:{run.id}:{failed.id}")
    )
    assert retry is not None
    retry.run_after = utc_now()
    session.commit()
    transport.failures.clear()

    second = run_evaluation_batch(session, run.id, provider)
    result_ids = list(
        session.scalars(select(EvaluationResult.id).where(EvaluationResult.run_id == run.id))
    )

    assert first.succeeded == 2
    assert first.failed == 1
    assert second.succeeded == 3
    assert second.failed == 0
    assert len(result_ids) == 3
    assert (
        sum(
            request.conversation.external_id == conversations[0].external_id
            for request in transport.requests
        )
        == 1
    )
    assert (
        sum(
            request.conversation.external_id == failed.external_id for request in transport.requests
        )
        == 2
    )
    assert session.get(EvaluationRun, run.id).status == RunStatus.SUCCEEDED


def test_exhausted_item_enters_manual_review_without_losing_successes(session: Session) -> None:
    run, conversations = _run_with_sample(session)
    failed = conversations[-1]
    retry = enqueue_job(
        session,
        "evaluation_item",
        {"run_id": run.id, "conversation_id": failed.id, "max_attempts": 2},
        f"evaluation-item:{run.id}:{failed.id}",
    )
    transport = FlakyTransport({failed.external_id})
    provider = EvaluationProvider(transport)

    first = run_evaluation_batch(session, run.id, provider)
    retry.run_after = utc_now()
    session.commit()
    second = run_evaluation_batch(session, run.id, provider)
    exhausted = session.get(Job, retry.id)

    assert first.succeeded == 2
    assert second.failed == 1
    assert exhausted is not None
    assert exhausted.status == JobStatus.MANUAL_REVIEW
    assert (
        len(
            list(session.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run.id)))
        )
        == 2
    )


def test_result_lineage_is_persisted_on_its_versioned_run(session: Session) -> None:
    run, conversations = _run_with_sample(session, count=1)
    transport = FlakyTransport()

    summary = run_evaluation_batch(session, run.id, EvaluationProvider(transport))
    result = session.scalar(select(EvaluationResult).where(EvaluationResult.run_id == run.id))
    call = session.scalar(
        select(ModelCallRecord).where(ModelCallRecord.evaluation_run_id == run.id)
    )

    assert summary.succeeded == 1
    assert result is not None
    assert result.conversation_id == conversations[0].id
    assert result.run.provider == "public-test-provider"
    assert result.run.model == "model-v9"
    assert result.run.model_parameters == {"temperature": 0}
    assert result.run.template.version == "template-v3"
    assert result.run.prompt_version.version == "prompt-v4"
    assert result.run.rule_version.version == "rules-v5"
    assert call is not None
    assert call.provider == "public-test-provider"
    assert call.model == "model-v9"


def test_provider_call_runs_outside_database_transaction(session: Session) -> None:
    run, _ = _run_with_sample(session, count=1)
    run_id = run.id
    session.expunge_all()

    class TransactionCheckingTransport(FlakyTransport):
        def __init__(self) -> None:
            super().__init__()
            self.transaction_states: list[bool] = []

        def evaluate(self, request: EvaluationRequest) -> ProviderEvaluation:
            self.transaction_states.append(session.in_transaction())
            return super().evaluate(request)

    transport = TransactionCheckingTransport()

    run_evaluation_batch(session, run_id, EvaluationProvider(transport))

    assert transport.transaction_states == [False]


def test_create_run_api_persists_versions_and_enqueues_the_batch(session: Session) -> None:
    existing_run, _ = _run_with_sample(session, count=1)

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session

    async def create_run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/api/evaluation/runs",
                json={
                    "sampling_batch_id": existing_run.sampling_batch_id,
                    "template_id": existing_run.template_id,
                    "prompt_version_id": existing_run.prompt_version_id,
                    "rule_version_id": existing_run.rule_version_id,
                    "provider": "public-test-provider",
                    "model": "model-v9",
                    "model_parameters": {"temperature": 0},
                },
            )

    try:
        response = asyncio.run(create_run())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    run = session.get(EvaluationRun, response.json()["id"])
    job = session.scalar(
        select(Job).where(Job.idempotency_key == f"evaluation-batch:{response.json()['id']}")
    )
    assert run is not None
    assert run.provider == "public-test-provider"
    assert run.model == "model-v9"
    assert run.template_id == existing_run.template_id
    assert run.prompt_version_id == existing_run.prompt_version_id
    assert run.rule_version_id == existing_run.rule_version_id
    assert job is not None
    assert job.kind == "evaluation_batch"
