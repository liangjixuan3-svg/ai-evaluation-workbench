from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.alerts.models import Alert, AlertResult
from app.alerts.router import get_evaluation_provider
from app.analysis.models import BadcaseCluster, ClusterMember, RootCauseSuggestion
from app.config import settings
from app.db import Base, get_session
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
from app.shared.enums import AlertStatus, Confidence, RootCause, RunStatus


class AttributionTransport:
    identity = ProviderIdentity(provider="test-real", model="attribution-v2")

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, request: object) -> object:
        raise AssertionError("evaluation is not expected")

    def attribute(self, request: AttributionRequest) -> ProviderAttribution:
        self.calls += 1
        return ProviderAttribution(
            root_cause=RootCause.MISUNDERSTANDING,
            reason="没有理解用户在询问到账时间",
            evidence=["请稍后。"],
            confidence=0.7,
        )

    def draft_qa(self, request: object) -> object:
        raise AssertionError("QA drafting is not expected")


@pytest.fixture
def issue_client() -> Iterator[tuple[TestClient, str]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with sessions() as session:
        cluster_id = _seed_issue(session)
    app = create_app()

    def override_session() -> Iterator[Session]:
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        yield client, cluster_id
    engine.dispose()


def test_issue_list_returns_real_cluster_summary(issue_client: tuple[TestClient, str]) -> None:
    client, cluster_id = issue_client

    response = client.get("/api/issues?status=pending")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {
        "pending_count": 1,
        "confirmed_count": 0,
        "impacted_count": 2,
        "missing_knowledge_count": 1,
    }
    assert payload["items"] == [
        {
            "id": cluster_id,
            "run_id": payload["items"][0]["run_id"],
            "scenario": "退款进度查询",
            "weakest_dimension": "completeness",
            "problem_summary": "没有说明退款到账时间",
            "impact_count": 2,
            "priority": "P1",
            "status": "pending",
            "suggestion": {
                "root_cause": "missing_knowledge",
                "confidence": "medium",
            },
            "created_at": payload["items"][0]["created_at"],
        }
    ]
    assert client.get("/api/issues?status=confirmed").json()["items"] == []


def test_issue_detail_returns_redacted_representative_samples(
    issue_client: tuple[TestClient, str],
) -> None:
    client, cluster_id = issue_client

    response = client.get(f"/api/issues/{cluster_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == cluster_id
    assert payload["alert"]["priority"] == "P1"
    assert payload["suggestion"]["reason"] == "知识库没有退款时效说明"
    assert payload["confirmation"] is None
    assert payload["task"] is None
    assert len(payload["samples"]) == 2
    assert payload["samples"][0]["score"] == 42.0
    transcript = str(payload["samples"][0]["messages"])
    assert "[PHONE]" in transcript
    assert "[ORDER_ID]" in transcript
    assert "13800138000" not in transcript
    assert "ORD-20260801-A1" not in transcript
    assert client.get("/api/issues/not-found").status_code == 404


def test_attribution_uses_overridable_provider_and_is_idempotent(
    issue_client: tuple[TestClient, str],
) -> None:
    client, cluster_id = issue_client
    transport = AttributionTransport()
    client.app.dependency_overrides[get_evaluation_provider] = lambda: EvaluationProvider(
        transport
    )

    first = client.post(f"/api/badcases/{cluster_id}/attribution")
    replay = client.post(f"/api/badcases/{cluster_id}/attribution")

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json()["root_cause"] == "misunderstanding"
    assert transport.calls == 1


def test_unconfigured_attribution_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_model", "")

    with pytest.raises(HTTPException) as error:
        get_evaluation_provider()

    assert error.value.status_code == 503


def test_explicit_cluster_confirmation_routes_one_task(
    issue_client: tuple[TestClient, str],
) -> None:
    client, cluster_id = issue_client
    body = {
        "actor": "林乔",
        "root_cause": "missing_knowledge",
        "evidence": ["已查看两条代表样本，确认缺少退款时效知识"],
        "confirm_cluster": True,
    }

    first = client.post(f"/api/badcases/{cluster_id}/confirm-attribution", json=body)
    replay = client.post(f"/api/badcases/{cluster_id}/confirm-attribution", json=body)
    detail = client.get(f"/api/issues/{cluster_id}").json()

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json() == replay.json()
    assert first.json()["type"] == "qa_review"
    assert detail["status"] == "confirmed"
    assert detail["confirmation"]["root_cause"] == "missing_knowledge"
    assert detail["task"]["id"] == first.json()["id"]


def _seed_issue(session: Session) -> str:
    now = datetime(2026, 8, 2, 1, tzinfo=UTC)
    source = DataSource(name="issue-workspace-source", kind="test")
    template = EvaluationTemplate(
        name="issue-workspace-template",
        version="v1",
        weights={"completeness": 1},
        threshold=Decimal(75),
        veto_rules={},
    )
    prompt = PromptVersion(
        name="issue-workspace-prompt",
        version="v1",
        content="evaluate",
        published_at=now,
    )
    rule = RuleVersion(kind="issue-workspace-rule", version="v1", config={})
    run = EvaluationRun(
        template=template,
        prompt_version=prompt,
        rule_version=rule,
        provider="test",
        model="judge-v1",
        model_parameters={},
        status=RunStatus.SUCCEEDED,
    )
    session.add_all((source, run))
    session.flush()
    results: list[EvaluationResult] = []
    for index, score in enumerate((42, 51), start=1):
        conversation = Conversation(
            data_source_id=source.id,
            external_id=f"refund-{index}",
            scenario="退款进度查询",
            body={
                "messages": [
                    {
                        "role": "user",
                        "content": "订单 ORD-20260801-A1 什么时候退款？电话 13800138000",
                    },
                    {"role": "assistant", "content": "请稍后。"},
                ]
            },
            occurred_at=now,
        )
        result = EvaluationResult(
            run=run,
            conversation=conversation,
            total_score=Decimal(score),
            dimension_scores={
                "correctness": 80,
                "completeness": score,
                "relevance": 75,
                "service_experience": 70,
                "compliance": 90,
            },
            passed=False,
            reason="没有说明退款到账时间",
            evidence=["请稍后。"],
            confidence=Confidence.MEDIUM,
        )
        session.add(result)
        results.append(result)
    session.flush()
    cluster = BadcaseCluster(
        run_id=run.id,
        scenario="退款进度查询",
        weakest_dimension="completeness",
        normalized_reason="没有说明退款到账时间",
        algorithm_version="badcase-grouping-v1",
        grouping_key="issue-workspace-refund-cluster",
        created_at=now,
    )
    session.add(cluster)
    session.flush()
    session.add_all(
        ClusterMember(
            cluster_id=cluster.id,
            evaluation_result_id=result.id,
            representative_rank=index,
        )
        for index, result in enumerate(results, start=1)
    )
    session.add(
        RootCauseSuggestion(
            cluster_id=cluster.id,
            evaluation_result_id=results[0].id,
            provider="test",
            model="attribution-v1",
            root_cause=RootCause.MISSING_KNOWLEDGE,
            reason="知识库没有退款时效说明",
            evidence=["请稍后。"],
            confidence=Confidence.MEDIUM,
            created_at=now,
        )
    )
    alert = Alert(
        kind="issue_spike",
        priority="P1",
        scenario="退款进度查询",
        root_cause=None,
        status=AlertStatus.OPEN,
        merge_key="issue-workspace-alert",
        baseline_value=Decimal("0.1"),
        current_value=Decimal(1),
        impact_count=2,
        window_started_at=now,
        window_ended_at=now,
    )
    session.add(alert)
    session.flush()
    session.add_all(
        AlertResult(alert_id=alert.id, evaluation_result_id=result.id) for result in results
    )
    session.commit()
    return cluster.id
