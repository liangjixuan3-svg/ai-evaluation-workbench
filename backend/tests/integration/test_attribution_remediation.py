from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.analysis.models import BadcaseCluster, ClusterMember, RootCauseSuggestion
from app.db import get_session
from app.evaluation.contracts import (
    AttributionRequest,
    ProviderAttribution,
    ProviderQADraft,
    QADraftRequest,
)
from app.evaluation.models import (
    EvaluationResult,
    EvaluationRun,
    EvaluationTemplate,
    PromptVersion,
    RuleVersion,
)
from app.evaluation.providers import EvaluationProvider, ProviderIdentity
from app.ingestion.models import Conversation, DataSource
from app.main import create_app
from app.remediation.models import QAEvidence, QAVersion
from app.remediation.router import get_remediation_provider
from app.remediation.service import (
    AttributionCommand,
    BulkConfirmationNotAllowed,
    IncompleteAttribution,
    confirm_attribution,
    generate_qa_draft,
)
from app.shared.audit import AuditEvent
from app.shared.enums import Confidence, RootCause, TaskType


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


class QATransport:
    identity = ProviderIdentity(provider="test", model="qa-v1")

    def evaluate(self, request: object) -> object:
        raise AssertionError("evaluation is not expected")

    def attribute(self, request: AttributionRequest) -> ProviderAttribution:
        raise AssertionError("attribution is not expected")

    def draft_qa(self, request: QADraftRequest) -> ProviderQADraft:
        assert request.conversation.messages[0].content == "退款规则需要主管批准。"
        return ProviderQADraft(
            content={
                "question": "退款何时到账？",
                "answer": "退款规则需要主管批准。",
                "applicability": "退款场景",
                "handling_steps": ["核实退款状态"],
                "estimated_time": "1 个工作日",
                "escalation": "规则不明确时转人工",
            },
            reason="基于代表对话生成。",
            evidence=["退款规则需要主管批准。"],
            confidence=0.9,
        )


def _cluster(
    session: Session, confidence: Confidence = Confidence.HIGH, members: int = 2
) -> BadcaseCluster:
    suffix = uuid4().hex
    source = DataSource(name=f"remediation-source-{confidence}-{members}-{suffix}", kind="test")
    template = EvaluationTemplate(
        name=f"remediation-template-{confidence}-{members}-{suffix}",
        version="1",
        weights={"correctness": 1},
        threshold=Decimal(80),
        veto_rules={},
    )
    prompt = PromptVersion(
        name=f"remediation-prompt-{confidence}-{members}-{suffix}", version="1", content="test"
    )
    rule = RuleVersion(
        kind=f"remediation-rule-{confidence}-{members}-{suffix}", version="1", config={}
    )
    run = EvaluationRun(
        template=template,
        prompt_version=prompt,
        rule_version=rule,
        provider="test",
        model="qa-v1",
        model_parameters={},
    )
    session.add_all((source, run))
    session.flush()
    cluster = BadcaseCluster(
        run_id=run.id,
        weakest_dimension="correctness",
        normalized_reason="refund policy",
        algorithm_version="v1",
        grouping_key=f"remediation-{confidence}-{members}-{suffix}",
    )
    session.add(cluster)
    session.flush()
    for index in range(members):
        conversation = Conversation(
            data_source=source,
            external_id=f"remediation-{confidence}-{members}-{suffix}-{index}",
            body={"messages": [{"role": "agent", "content": "退款规则需要主管批准。"}]},
        )
        result = EvaluationResult(
            run=run,
            conversation=conversation,
            total_score=Decimal(40),
            dimension_scores={"correctness": 40},
            passed=False,
            reason="退款规则未知",
            evidence=["退款规则需要主管批准。"],
            confidence=confidence,
        )
        session.add(result)
        session.flush()
        session.add(
            ClusterMember(
                cluster_id=cluster.id,
                evaluation_result_id=result.id,
                representative_rank=index + 1,
            )
        )
    session.flush()
    representative = session.scalar(
        select(ClusterMember)
        .where(ClusterMember.cluster_id == cluster.id)
        .order_by(ClusterMember.representative_rank)
    )
    assert representative is not None
    session.add(
        RootCauseSuggestion(
            cluster_id=cluster.id,
            evaluation_result_id=representative.evaluation_result_id,
            provider="test",
            model="qa-v1",
            root_cause=RootCause.MISSING_KNOWLEDGE,
            reason="缺少退款规则",
            evidence=["退款规则需要主管批准。"],
            confidence=confidence,
        )
    )
    session.commit()
    return cluster


def test_high_confidence_bulk_confirmation_routes_once_and_preserves_suggestion(
    session: Session,
) -> None:
    cluster = _cluster(session)
    suggestion = session.scalar(
        select(RootCauseSuggestion).where(RootCauseSuggestion.cluster_id == cluster.id)
    )
    assert suggestion is not None

    task = confirm_attribution(
        session,
        AttributionCommand(
            cluster_id=cluster.id,
            actor="operator-1",
            root_cause=RootCause.MISSING_KNOWLEDGE,
            member_ids=(),
            bulk=True,
            evidence=["已核对退款规则"],
        ),
    )
    replay = confirm_attribution(
        session,
        AttributionCommand(
            cluster_id=cluster.id,
            actor="operator-1",
            root_cause=RootCause.MISSING_KNOWLEDGE,
            member_ids=(),
            bulk=True,
            evidence=["已核对退款规则"],
        ),
    )

    assert task is not None
    assert task.type == TaskType.QA_REVIEW
    assert replay is not None and replay.id == task.id
    assert session.get(RootCauseSuggestion, suggestion.id).root_cause == RootCause.MISSING_KNOWLEDGE
    assert all(
        member.confirmed_root_cause == RootCause.MISSING_KNOWLEDGE
        for member in session.scalars(
            select(ClusterMember).where(ClusterMember.cluster_id == cluster.id)
        )
    )
    assert (
        len(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "attribution_confirmed",
                    AuditEvent.entity_id == cluster.id,
                )
            ).all()
        )
        == 2
    )


def test_medium_confidence_requires_each_member_human_confirmation(session: Session) -> None:
    cluster = _cluster(session, Confidence.MEDIUM)
    member_ids = list(
        session.scalars(
            select(ClusterMember.evaluation_result_id).where(ClusterMember.cluster_id == cluster.id)
        )
    )

    with pytest.raises(BulkConfirmationNotAllowed):
        confirm_attribution(
            session,
            AttributionCommand(
                cluster_id=cluster.id,
                actor="operator-1",
                root_cause=RootCause.MISSING_KNOWLEDGE,
                member_ids=(),
                bulk=True,
                evidence=["reviewed"],
            ),
        )
    with pytest.raises(IncompleteAttribution):
        generate_qa_draft(session, cluster.id, EvaluationProvider(QATransport()))
    assert (
        confirm_attribution(
            session,
            AttributionCommand(
                cluster_id=cluster.id,
                actor="operator-1",
                root_cause=RootCause.MISSING_KNOWLEDGE,
                member_ids=(member_ids[0],),
                evidence=["member 1 reviewed"],
            ),
        )
        is None
    )
    task = confirm_attribution(
        session,
        AttributionCommand(
            cluster_id=cluster.id,
            actor="operator-1",
            root_cause=RootCause.MISSING_KNOWLEDGE,
            member_ids=(member_ids[1],),
            evidence=["member 2 reviewed"],
        ),
    )

    assert task is not None and task.type == TaskType.QA_REVIEW


def test_only_confirmed_missing_knowledge_generates_replay_safe_qa_with_evidence(
    session: Session,
) -> None:
    cluster = _cluster(session)
    confirm_attribution(
        session,
        AttributionCommand(
            cluster_id=cluster.id,
            actor="operator-1",
            root_cause=RootCause.MISSING_KNOWLEDGE,
            member_ids=(),
            bulk=True,
            evidence=["reviewed"],
        ),
    )
    provider = EvaluationProvider(QATransport())

    draft = generate_qa_draft(session, cluster.id, provider)
    replay = generate_qa_draft(session, cluster.id, provider)

    assert replay.id == draft.id
    assert draft.current_version_number == 1
    assert len(session.scalars(select(QAVersion).where(QAVersion.draft_id == draft.id)).all()) == 1
    assert {
        item.source_type
        for item in session.scalars(
            select(QAEvidence).where(QAEvidence.qa_version_id == draft.current_version.id)
        )
    } == {"conversation", "ai_attribution"}


def test_remediation_api_uses_overridable_session_and_provider(session: Session) -> None:
    cluster = _cluster(session)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_remediation_provider] = lambda: EvaluationProvider(QATransport())

    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            confirmed = await client.post(
                f"/api/badcases/{cluster.id}/confirm-attribution",
                json={
                    "actor": "operator-1",
                    "root_cause": "missing_knowledge",
                    "bulk": True,
                    "evidence": ["reviewed"],
                },
            )
            assert confirmed.status_code == 200
            return await client.post(f"/api/badcases/{cluster.id}/qa-drafts")

    try:
        response = asyncio.run(request())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "pending_review"
