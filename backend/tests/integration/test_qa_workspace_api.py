from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.alerts.models import Task
from app.analysis.models import BadcaseCluster, ClusterMember, RootCauseSuggestion
from app.config import settings
from app.db import Base, get_session
from app.evaluation.contracts import ProviderQADraft, QADraftContent, QADraftRequest
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
from app.remediation.router import get_remediation_provider
from app.shared.enums import Confidence, RootCause, RunStatus, TaskType


class QATransport:
    identity = ProviderIdentity(provider="test-real", model="qa-v2")

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, request: object) -> object:
        raise AssertionError("evaluation is not expected")

    def attribute(self, request: object) -> object:
        raise AssertionError("attribution is not expected")

    def draft_qa(self, request: QADraftRequest) -> ProviderQADraft:
        self.calls += 1
        return ProviderQADraft(
            content=QADraftContent(
                question="退款什么时候到账？",
                answer="退款原路退回，通常在审核通过后 1 至 3 个工作日到账。",
                applicability="退款状态为审核通过",
                handling_steps=["查询退款状态", "告知预计到账时间"],
                estimated_time="1 至 3 个工作日",
                escalation="超过 3 个工作日仍未到账时转人工",
            ),
            reason="根据知识缺失问题生成退款到账时效 QA",
            evidence=["请稍后。"],
            confidence=0.8,
        )


@pytest.fixture
def qa_client() -> Iterator[tuple[TestClient, str, str]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with sessions() as session:
        task_id, cluster_id = _seed_qa_task(session)
    app = create_app()

    def override_session() -> Iterator[Session]:
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        yield client, task_id, cluster_id
    engine.dispose()


def test_qa_workspace_lists_real_knowledge_tasks(
    qa_client: tuple[TestClient, str, str],
) -> None:
    client, task_id, cluster_id = qa_client

    response = client.get("/api/qa-workspace?status=pending")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {
        "awaiting_generation_count": 1,
        "pending_review_count": 0,
        "approved_count": 0,
        "rejected_count": 0,
    }
    assert payload["items"] == [
        {
            "task_id": task_id,
            "cluster_id": cluster_id,
            "scenario": "退款进度查询",
            "problem_summary": "没有说明退款到账时间",
            "impact_count": 1,
            "priority": "P1",
            "task_status": "open",
            "state": "awaiting_generation",
            "confidence": None,
            "updated_at": payload["items"][0]["updated_at"],
        }
    ]
    assert client.get("/api/qa-workspace?status=approved").json()["items"] == []


def test_qa_workspace_detail_returns_redacted_samples_and_empty_draft(
    qa_client: tuple[TestClient, str, str],
) -> None:
    client, task_id, cluster_id = qa_client

    response = client.get(f"/api/qa-workspace/{task_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == task_id
    assert payload["cluster_id"] == cluster_id
    assert payload["state"] == "awaiting_generation"
    assert payload["draft"] is None
    assert payload["confirmation"]["root_cause"] == "missing_knowledge"
    assert len(payload["samples"]) == 1
    transcript = str(payload["samples"][0]["messages"])
    assert "[PHONE]" in transcript
    assert "13800138000" not in transcript
    assert client.get("/api/qa-workspace/not-found").status_code == 404


def test_qa_generation_uses_real_overridable_provider_once(
    qa_client: tuple[TestClient, str, str],
) -> None:
    client, task_id, _ = qa_client
    transport = QATransport()
    client.app.dependency_overrides[get_remediation_provider] = lambda: EvaluationProvider(
        transport
    )

    first = client.post(f"/api/qa-workspace/{task_id}/generate")
    replay = client.post(f"/api/qa-workspace/{task_id}/generate")
    detail = client.get(f"/api/qa-workspace/{task_id}").json()

    assert first.status_code == 200, first.text
    assert replay.status_code == 200
    assert first.json() == replay.json()
    assert transport.calls == 1
    assert detail["state"] == "pending_review"
    assert detail["draft"]["content"]["question"] == "退款什么时候到账？"


def test_unconfigured_qa_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_model", "")

    with pytest.raises(HTTPException) as error:
        get_remediation_provider()

    assert error.value.status_code == 503


def test_qa_approval_requires_business_evidence_and_completes_task(
    qa_client: tuple[TestClient, str, str],
) -> None:
    client, task_id, _ = qa_client
    draft_id = _generate_draft(client, task_id)

    missing_evidence = client.post(
        f"/api/qa-drafts/{draft_id}/approve",
        json={"actor": "林乔", "edits": {}},
    )
    approved = client.post(
        f"/api/qa-drafts/{draft_id}/approve",
        json={
            "actor": "林乔",
            "edits": {
                "question": "退款审核通过后多久能到账？",
                "answer": "款项原路退回，通常 1 至 3 个工作日到账。",
                "applicability": "退款状态为审核通过",
                "handling_steps": ["查询退款状态", "告知到账时效"],
                "estimated_time": "1 至 3 个工作日",
                "escalation": "超过 3 个工作日仍未到账时转人工",
                "business_evidence": [
                    {
                        "source_ref": "退款规则 2026 V3",
                        "excerpt": "退款审核通过后，款项原路退回，通常 1 至 3 个工作日到账。",
                    }
                ],
            },
        },
    )

    assert missing_evidence.status_code == 422
    assert approved.status_code == 200, approved.text
    assert approved.json()["version_number"] == 2
    detail = client.get(f"/api/qa-workspace/{task_id}").json()
    assert detail["state"] == "approved"
    assert detail["task_status"] == "done"
    assert detail["draft"]["content"]["question"] == "退款审核通过后多久能到账？"
    assert detail["draft"]["evidence"][0]["source_ref"] == "退款规则 2026 V3"


def test_qa_rejection_requires_reason_and_cancels_task(
    qa_client: tuple[TestClient, str, str],
) -> None:
    client, task_id, _ = qa_client
    draft_id = _generate_draft(client, task_id)

    missing_reason = client.post(
        f"/api/qa-drafts/{draft_id}/reject",
        json={"actor": "林乔", "reason": ""},
    )
    rejected = client.post(
        f"/api/qa-drafts/{draft_id}/reject",
        json={"actor": "林乔", "reason": "公司现行规则不支持该到账时效"},
    )

    assert missing_reason.status_code == 422
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    detail = client.get(f"/api/qa-workspace/{task_id}").json()
    assert detail["state"] == "rejected"
    assert detail["task_status"] == "cancelled"
    assert detail["draft"]["rejection_reason"] == "公司现行规则不支持该到账时效"


@pytest.mark.parametrize(
    ("export_format", "media_type", "filename"),
    [
        ("json", "application/json", "qa-export.json"),
        ("csv", "text/csv", "qa-export.csv"),
    ],
)
def test_approved_qa_can_be_downloaded_directly(
    qa_client: tuple[TestClient, str, str],
    export_format: str,
    media_type: str,
    filename: str,
) -> None:
    client, task_id, _ = qa_client
    draft_id = _generate_draft(client, task_id)
    pending_download = client.post(
        "/api/qa-exports/download",
        json={"actor": "林乔", "draft_ids": [draft_id], "format": export_format},
    )
    client.post(
        f"/api/qa-drafts/{draft_id}/approve",
        json={
            "actor": "林乔",
            "edits": {
                "business_evidence": [
                    {
                        "source_ref": "退款规则 2026 V3",
                        "excerpt": "退款通常在审核通过后 1 至 3 个工作日到账。",
                    }
                ]
            },
        },
    )

    response = client.post(
        "/api/qa-exports/download",
        json={"actor": "林乔", "draft_ids": [draft_id], "format": export_format},
    )

    assert pending_download.status_code == 422
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(media_type)
    assert filename in response.headers["content-disposition"]
    assert response.content


def _generate_draft(client: TestClient, task_id: str) -> str:
    client.app.dependency_overrides[get_remediation_provider] = lambda: EvaluationProvider(
        QATransport()
    )
    response = client.post(f"/api/qa-workspace/{task_id}/generate")
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _seed_qa_task(session: Session) -> tuple[str, str]:
    now = datetime(2026, 8, 10, 1, tzinfo=UTC)
    source = DataSource(name="qa-workspace-source", kind="test")
    template = EvaluationTemplate(
        name="qa-workspace-template",
        version="v1",
        weights={"completeness": 1},
        threshold=Decimal(75),
        veto_rules={},
    )
    prompt = PromptVersion(
        name="qa-workspace-prompt", version="v1", content="evaluate", published_at=now
    )
    rule = RuleVersion(kind="qa-workspace-rule", version="v1", config={})
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
    conversation = Conversation(
        data_source_id=source.id,
        external_id="qa-refund-1",
        scenario="退款进度查询",
        body={
            "messages": [
                {"role": "user", "content": "退款什么时候到账？电话 13800138000"},
                {"role": "assistant", "content": "请稍后。"},
            ]
        },
        occurred_at=now,
    )
    result = EvaluationResult(
        run=run,
        conversation=conversation,
        total_score=Decimal(42),
        dimension_scores={
            "correctness": 60,
            "completeness": 30,
            "relevance": 70,
            "service_experience": 65,
            "compliance": 90,
        },
        passed=False,
        reason="没有说明退款到账时间",
        evidence=["请稍后。"],
        confidence=Confidence.MEDIUM,
    )
    session.add(result)
    session.flush()
    cluster = BadcaseCluster(
        run_id=run.id,
        scenario="退款进度查询",
        weakest_dimension="completeness",
        normalized_reason="没有说明退款到账时间",
        algorithm_version="badcase-grouping-v1",
        grouping_key="qa-workspace-refund-cluster",
        created_at=now,
    )
    session.add(cluster)
    session.flush()
    member = ClusterMember(
        cluster_id=cluster.id,
        evaluation_result_id=result.id,
        representative_rank=1,
        confirmed_root_cause=RootCause.MISSING_KNOWLEDGE,
        confirmed_by="林乔",
        confirmed_at=now,
    )
    suggestion = RootCauseSuggestion(
        cluster_id=cluster.id,
        evaluation_result_id=result.id,
        provider="test",
        model="attribution-v1",
        root_cause=RootCause.MISSING_KNOWLEDGE,
        reason="知识库没有退款到账时效",
        evidence=["请稍后。"],
        confidence=Confidence.MEDIUM,
        created_at=now,
    )
    task = Task(
        type=TaskType.QA_REVIEW,
        cluster_id=cluster.id,
        title="补充退款到账时效知识",
        priority="P1",
        payload={"root_cause": "missing_knowledge", "evidence": ["人工确认知识缺失"]},
    )
    session.add_all((member, suggestion, task))
    session.commit()
    return task.id, cluster.id
