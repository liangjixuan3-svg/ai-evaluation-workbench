from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.calibration.models import CalibrationBatch, CalibrationReview
from app.db import Base, get_session
from app.evaluation.models import (
    EvaluationResult,
    EvaluationRun,
    EvaluationTemplate,
    ModelCallRecord,
    PromptVersion,
    RuleVersion,
)
from app.ingestion.models import Conversation, DataSource
from app.main import create_app
from app.quality_standards.models import QualityStandard, QualityStandardVersion
from app.shared.enums import CalibrationBatchStatus, Confidence, RunStatus


@pytest.fixture
def calibration_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with sessions() as session:
        _seed_results(session)
    app = create_app()

    def override_session() -> Iterator[Session]:
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        yield client, sessions
    engine.dispose()


def test_calibration_workspace_and_detail_expose_locked_evaluation_without_sensitive_data(
    calibration_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = calibration_client
    before_calls = _model_call_count(sessions)

    ensured = client.post("/api/calibration/batches/today/ensure")
    workspace = client.get("/api/calibration/workspace?status=pending")

    assert ensured.status_code == 200, ensured.text
    assert workspace.status_code == 200, workspace.text
    payload = workspace.json()
    assert payload["summary"] == {
        "reviewed": 0,
        "total": 3,
        "pending": 3,
        "agreement_rate": None,
        "top_disagreement_dimension": None,
    }
    assert payload["items"][0]["selection_reason"] == "low_confidence"

    review_id = payload["items"][0]["review_id"]
    detail = client.get(f"/api/calibration/reviews/{review_id}")

    assert detail.status_code == 200, detail.text
    detail_payload = detail.json()
    assert detail_payload["conversation"]["messages"][0]["content"] == "手机 [PHONE]"
    assert detail_payload["evaluation"] == {
        "total_score": 82.0,
        "dimension_scores": {
            "correctness": 80,
            "completeness": 70,
            "relevance": 90,
            "service_experience": 75,
            "compliance": 95,
        },
        "passed": True,
        "confidence": "low",
        "reason": "说明清楚",
        "evidence": ["预计 1 至 3 个工作日"],
        "severe_factual_error": False,
        "severe_compliance_error": False,
    }
    assert detail_payload["locked_rule"]["quality_standard"]["version_number"] == 1
    assert detail_payload["locked_rule"]["prompt"]["content"] == "使用公司质量标准评测。"
    assert detail_payload["locked_rule"]["model"] == {
        "provider": "seed-provider",
        "model": "seed-model-v1",
        "parameters": {"temperature": 0},
    }
    transcript = str(detail_payload)
    assert "13800138000" not in transcript
    assert "linqiao@example.com" not in transcript
    assert "ORD-20260810-A1" not in transcript
    assert "[PHONE]" in transcript
    assert "[EMAIL]" in transcript
    assert "[ORDER_ID]" in transcript
    assert _model_call_count(sessions) == before_calls
    assert client.get("/api/calibration/reviews/not-found").status_code == 404


def test_calibration_review_submission_is_idempotent_and_completes_batch(
    calibration_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = calibration_client
    before_calls = _model_call_count(sessions)
    workspace = client.post("/api/calibration/batches/today/ensure")

    assert workspace.status_code == 200, workspace.text
    items = client.get("/api/calibration/workspace?status=all").json()["items"]
    first_id, second_id, third_id = (item["review_id"] for item in items)
    agreed = client.post(f"/api/calibration/reviews/{first_id}/agree", json={"actor": " 林乔 "})
    invalid_actor = client.post(f"/api/calibration/reviews/{second_id}/agree", json={"actor": " "})
    missing_basis = client.post(
        f"/api/calibration/reviews/{second_id}/disagree",
        json={
            "actor": "林乔",
            "corrected_passed": False,
            "disagreement_dimension": "completeness",
        },
    )
    blank_basis = client.post(
        f"/api/calibration/reviews/{second_id}/disagree",
        json={
            "actor": "林乔",
            "corrected_passed": False,
            "disagreement_dimension": "completeness",
            "review_basis": "   ",
        },
    )
    overlong_basis = client.post(
        f"/api/calibration/reviews/{second_id}/disagree",
        json={
            "actor": "林乔",
            "corrected_passed": False,
            "disagreement_dimension": "completeness",
            "review_basis": "x" * 1001,
        },
    )
    disagreed = client.post(
        f"/api/calibration/reviews/{second_id}/disagree",
        json={
            "actor": "林乔",
            "corrected_passed": False,
            "disagreement_dimension": "completeness",
            "review_basis": " 公司制度要求主动说明预计处理时效。 ",
        },
    )
    replay = client.post(f"/api/calibration/reviews/{second_id}/agree", json={"actor": "其他人"})
    final_agreement = client.post(
        f"/api/calibration/reviews/{third_id}/agree", json={"actor": "林乔"}
    )

    assert agreed.status_code == 200, agreed.text
    assert agreed.json()["agreed"] is True
    assert agreed.json()["reviewed_by"] == "林乔"
    assert invalid_actor.status_code == 422
    assert missing_basis.status_code == 422
    assert blank_basis.status_code == 422
    assert overlong_basis.status_code == 422
    assert disagreed.status_code == 200, disagreed.text
    assert disagreed.json()["include_in_regression"] is True
    assert disagreed.json()["review_basis"] == "公司制度要求主动说明预计处理时效。"
    assert replay.status_code == 200, replay.text
    assert replay.json() == disagreed.json()
    assert final_agreement.status_code == 200, final_agreement.text
    assert _model_call_count(sessions) == before_calls
    with sessions() as session:
        batch = session.scalar(select(CalibrationBatch))
        result = session.get(CalibrationReview, second_id)
        assert batch is not None
        assert result is not None
        assert batch.status is CalibrationBatchStatus.COMPLETED
        assert result.reviewed_by == "林乔"
        assert result.review_basis == "公司制度要求主动说明预计处理时效。"


def _model_call_count(sessions: sessionmaker[Session]) -> int:
    with sessions() as session:
        return int(session.scalar(select(func.count()).select_from(ModelCallRecord)) or 0)


def _seed_results(session: Session) -> None:
    now = datetime.now(UTC)
    source = DataSource(name="calibration-api-source", kind="test")
    standard = QualityStandard(name="客服质量标准", status="published")
    standard_version = QualityStandardVersion(
        standard=standard,
        version_number=1,
        source_filename="quality-standard.docx",
        source_sha256="a" * 64,
        source_path="/tmp/quality-standard.docx",
        rules=_quality_rules(),
        published_at=now,
    )
    template = EvaluationTemplate(
        name="calibration-api-template",
        version="v1",
        weights={"completeness": 1},
        threshold=Decimal("80.00"),
        veto_rules={},
    )
    prompt = PromptVersion(
        name="calibration-api-prompt",
        version="v1",
        content="使用公司质量标准评测。",
        published_at=now,
    )
    rule = RuleVersion(kind="calibration-api-rule", version="v1", config={})
    run = EvaluationRun(
        template=template,
        prompt_version=prompt,
        rule_version=rule,
        quality_standard_version=standard_version,
        provider="seed-provider",
        model="seed-model-v1",
        model_parameters={"temperature": 0},
        status=RunStatus.SUCCEEDED,
        completed_at=now,
    )
    session.add_all((source, run))
    session.flush()
    results = [
        _result(session, source, run, 1, Confidence.LOW, "82.00"),
        _result(session, source, run, 2, Confidence.HIGH, "78.00"),
        _result(session, source, run, 3, Confidence.HIGH, "55.00", severe=True),
    ]
    session.add(
        ModelCallRecord(
            evaluation_run_id=run.id,
            provider="seed-provider",
            model="seed-model-v1",
            operation="evaluation",
            input_tokens=10,
            output_tokens=10,
            estimated_cost=Decimal("0.001"),
            status="succeeded",
            duration_ms=20,
        )
    )
    session.add_all(results)
    session.commit()


def _result(
    session: Session,
    source: DataSource,
    run: EvaluationRun,
    index: int,
    confidence: Confidence,
    score: str,
    *,
    severe: bool = False,
) -> EvaluationResult:
    conversation = Conversation(
        data_source_id=source.id,
        external_id=f"calibration-api-{index}",
        scenario="退款进度查询",
        body={
            "messages": [
                {
                    "role": "user",
                    "content": "手机 13800138000",
                    "metadata": {
                        "email": "linqiao@example.com",
                        "order": ["ORD-20260810-A1"],
                    },
                },
                {"role": "assistant", "content": "预计 1 至 3 个工作日"},
            ]
        },
        occurred_at=datetime.now(UTC),
    )
    return EvaluationResult(
        run=run,
        conversation=conversation,
        total_score=Decimal(score),
        dimension_scores={
            "correctness": 80,
            "completeness": 70,
            "relevance": 90,
            "service_experience": 75,
            "compliance": 95,
        },
        passed=True,
        reason="说明清楚",
        evidence=["预计 1 至 3 个工作日"],
        confidence=confidence,
        severe_factual_error=severe,
        created_at=datetime.now(UTC),
    )


def _quality_rules() -> dict[str, object]:
    return {
        "threshold": 80,
        "weights": {
            "correctness": 0.2,
            "completeness": 0.2,
            "relevance": 0.2,
            "service_experience": 0.2,
            "compliance": 0.2,
        },
        "anchors": [
            {"level": level, "description": f"{level} 描述"}
            for level in ("excellent", "good", "acceptable", "poor", "unacceptable")
        ],
        "common_rules": [],
        "scenarios": [],
    }
