from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.alerts.models import Alert, AlertResult
from app.alerts.rules import AlertConfig, AlertMetrics, evaluate_alert_rules
from app.alerts.service import merge_alert
from app.analysis.models import ClusterMember, RootCauseSuggestion
from app.analysis.service import attribute_cluster, cluster_badcases, persist_clusters
from app.db import get_session
from app.evaluation.contracts import AttributionRequest, ProviderAttribution
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
from app.shared.enums import Confidence, RootCause


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


class AttributionTransport:
    identity = ProviderIdentity(provider="test", model="attribution-v1")

    def evaluate(self, request: object) -> object:
        raise AssertionError("evaluation is not expected during attribution")

    def attribute(self, request: AttributionRequest) -> ProviderAttribution:
        return ProviderAttribution(
            root_cause=RootCause.MISSING_KNOWLEDGE,
            reason="The agent did not know the refund policy.",
            evidence=["Refund policy requires manager approval."],
            confidence=0.91,
        )

    def draft_qa(self, request: object) -> object:
        raise AssertionError("QA drafting is not expected during attribution")


class InvalidAttributionTransport(AttributionTransport):
    def attribute(self, request: AttributionRequest) -> ProviderAttribution:
        return ProviderAttribution(
            root_cause=RootCause.MISSING_KNOWLEDGE,
            reason="Invalid evidence must be rejected by the public provider boundary.",
            evidence=["not present in the transcript"],
            confidence=0.91,
        )


def _failed_results(session: Session) -> list[EvaluationResult]:
    source = DataSource(name="badcase-source", kind="simulated")
    template = EvaluationTemplate(
        name="badcase-template",
        version="1",
        weights={"correctness": 1},
        threshold=Decimal("80.00"),
        veto_rules={},
    )
    prompt = PromptVersion(name="badcase-prompt", version="1", content="Evaluate")
    rule = RuleVersion(kind="badcase-rule", version="1", config={})
    run = EvaluationRun(
        template=template,
        prompt_version=prompt,
        rule_version=rule,
        provider="test",
        model="attribution-v1",
        model_parameters={},
    )
    created_at = datetime(2026, 7, 30, tzinfo=UTC)
    results: list[EvaluationResult] = []
    for index, (reason, confidence, created_offset) in enumerate(
        (
            ("Missing refund policy details!", Confidence.LOW, 4),
            ("missing   refund policy details", Confidence.HIGH, 3),
            ("MISSING REFUND POLICY DETAILS.", Confidence.HIGH, 1),
            ("Missing refund policy details", Confidence.MEDIUM, 2),
        )
    ):
        conversation = Conversation(
            data_source=source,
            external_id=f"badcase-{index}",
            scenario="refund",
            body={
                "messages": [
                    {
                        "role": "agent",
                        "content": "Refund policy requires manager approval.",
                    }
                ]
            },
        )
        results.append(
            EvaluationResult(
                run=run,
                conversation=conversation,
                total_score=Decimal("40.00"),
                dimension_scores={"correctness": 20, "completeness": 60},
                passed=False,
                reason=reason,
                evidence=["Refund policy requires manager approval."],
                confidence=confidence,
                created_at=created_at + timedelta(minutes=created_offset),
            )
        )
    session.add_all(results)
    session.commit()
    return results


def _config() -> AlertConfig:
    return AlertConfig(
        min_samples=2,
        spike_delta=0.15,
        priority_scenarios=frozenset({"refund"}),
        priority_scenario_failure_rate=0.10,
        overall_drop_delta=0.08,
        merge_window=timedelta(hours=6),
    )


def test_clusters_persist_normalized_reason_and_rank_representatives(session: Session) -> None:
    results = _failed_results(session)

    drafts = cluster_badcases(results)
    clusters = persist_clusters(session, drafts)
    members = list(
        session.scalars(
            select(ClusterMember)
            .where(ClusterMember.cluster_id == clusters[0].id)
            .order_by(ClusterMember.representative_rank)
        )
    )

    assert len(drafts) == 1
    assert drafts[0].normalized_reason == "missing refund policy details"
    assert clusters[0].algorithm_version == "badcase-grouping-v1"
    assert len(members) == 4
    assert [member.evaluation_result_id for member in members if member.representative_rank] == [
        results[2].id,
        results[1].id,
        results[3].id,
    ]


def test_attribution_is_validated_and_human_confirmable_later(session: Session) -> None:
    cluster = persist_clusters(session, cluster_badcases(_failed_results(session)))[0]
    provider = EvaluationProvider(AttributionTransport())

    suggestion = attribute_cluster(session, cluster.id, provider)

    assert suggestion.root_cause == RootCause.MISSING_KNOWLEDGE
    assert suggestion.confidence == Confidence.HIGH
    assert suggestion.evidence == ["Refund policy requires manager approval."]
    member = session.scalar(select(ClusterMember).where(ClusterMember.cluster_id == cluster.id))
    assert member is not None
    assert member.confirmed_root_cause is None
    with pytest.raises(ValueError, match="evidence must be quoted"):
        attribute_cluster(session, cluster.id, EvaluationProvider(InvalidAttributionTransport()))
    assert (
        session.scalar(
            select(RootCauseSuggestion).where(RootCauseSuggestion.cluster_id == cluster.id)
        )
        == suggestion
    )


def test_merge_window_keeps_one_open_alert_and_all_result_links(session: Session) -> None:
    results = _failed_results(session)
    config = _config()
    start = datetime(2026, 7, 30, tzinfo=UTC)
    first = evaluate_alert_rules(
        AlertMetrics(
            failures=4,
            samples=10,
            scenario="refund",
            root_cause=RootCause.MISSING_KNOWLEDGE,
            result_ids=tuple(result.id for result in results[:2]),
            window_started_at=start,
            window_ended_at=start + timedelta(hours=1),
        ),
        AlertMetrics(
            failures=1,
            samples=10,
            scenario="refund",
            root_cause=RootCause.MISSING_KNOWLEDGE,
            result_ids=(),
            window_started_at=start - timedelta(days=1),
            window_ended_at=start,
        ),
        config,
    )[0]
    second = evaluate_alert_rules(
        AlertMetrics(
            failures=4,
            samples=10,
            scenario="refund",
            root_cause=RootCause.MISSING_KNOWLEDGE,
            result_ids=tuple(result.id for result in results[2:]),
            window_started_at=start + timedelta(hours=2),
            window_ended_at=start + timedelta(hours=3),
        ),
        AlertMetrics(
            failures=1,
            samples=10,
            scenario="refund",
            root_cause=RootCause.MISSING_KNOWLEDGE,
            result_ids=(),
            window_started_at=start - timedelta(days=1),
            window_ended_at=start,
        ),
        config,
    )[0]

    alert = merge_alert(session, first)
    merged = merge_alert(session, second)

    assert merged.id == alert.id
    assert merged.impact_count == 4
    assert session.scalars(select(Alert)).all() == [alert]
    assert len(session.scalars(select(AlertResult)).all()) == 4


def test_alert_api_uses_session_override_and_returns_evidence(session: Session) -> None:
    cluster = persist_clusters(session, cluster_badcases(_failed_results(session)))[0]
    attribute_cluster(session, cluster.id, EvaluationProvider(AttributionTransport()))
    result_ids = tuple(
        session.scalars(
            select(ClusterMember.evaluation_result_id).where(ClusterMember.cluster_id == cluster.id)
        )
    )
    signal = evaluate_alert_rules(
        AlertMetrics(
            failures=4,
            samples=10,
            scenario="refund",
            root_cause=RootCause.MISSING_KNOWLEDGE,
            result_ids=result_ids,
            window_started_at=datetime(2026, 7, 30, tzinfo=UTC),
            window_ended_at=datetime(2026, 7, 30, 1, tzinfo=UTC),
        ),
        AlertMetrics(
            failures=1,
            samples=10,
            scenario="refund",
            root_cause=RootCause.MISSING_KNOWLEDGE,
            result_ids=(),
            window_started_at=datetime(2026, 7, 29, tzinfo=UTC),
            window_ended_at=datetime(2026, 7, 30, tzinfo=UTC),
        ),
        _config(),
    )[0]
    alert = merge_alert(session, signal)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session

    async def request(path: str) -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)

    try:
        workbench = asyncio.run(request("/api/workbench"))
        detail = asyncio.run(request(f"/api/alerts/{alert.id}"))
    finally:
        app.dependency_overrides.clear()

    assert workbench.status_code == 200
    assert workbench.json()["alerts"][0]["id"] == alert.id
    assert detail.status_code == 200
    assert set(detail.json()["result_ids"]) == set(result_ids)
    assert detail.json()["root_cause_suggestion"]["confidence"] == "high"
