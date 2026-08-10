from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.alerts.models import Alert, AlertResult, Task
from app.analysis.models import BadcaseCluster, ClusterMember
from app.db import Base, get_session
from app.evaluation.contracts import EvaluationRequest, ProviderEvaluation
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
from app.remediation.models import QADraft, QAVersion
from app.retest.models import RetestRun, RetestSample
from app.retest.router import get_retest_provider
from app.shared.enums import (
    AlertStatus,
    Confidence,
    QADraftStatus,
    RetestStatus,
    RootCause,
    RunStatus,
    TaskStatus,
    TaskType,
)


class PassingRetestTransport:
    identity = ProviderIdentity(provider="test", model="judge-v1")

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, request: EvaluationRequest) -> ProviderEvaluation:
        self.calls += 1
        evidence = request.conversation.messages[-1].content
        return ProviderEvaluation(
            dimensions={
                "correctness": 90,
                "completeness": 90,
                "relevance": 90,
                "service_experience": 90,
                "compliance": 90,
            },
            reason="回复符合发布后的规则。",
            evidence=[evidence],
            confidence=0.95,
        )

    def attribute(self, request: object) -> object:
        raise AssertionError("attribution is not expected")

    def draft_qa(self, request: object) -> object:
        raise AssertionError("draft generation is not expected")


class FailSecondRetestTransport(PassingRetestTransport):
    def evaluate(self, request: EvaluationRequest) -> ProviderEvaluation:
        if self.calls == 1:
            self.calls += 1
            raise RuntimeError("模型暂时不可用")
        return super().evaluate(request)


class SupersedingRetestTransport(PassingRetestTransport):
    def __init__(self, sessions: sessionmaker[Session], run_id: str) -> None:
        super().__init__()
        self.sessions = sessions
        self.run_id = run_id

    def evaluate(self, request: EvaluationRequest) -> ProviderEvaluation:
        with self.sessions() as session:
            run = session.get(RetestRun, self.run_id)
            assert run is not None
            run.execution_token = "new-worker-token"
            session.commit()
        return super().evaluate(request)


@pytest.fixture
def retest_client() -> Iterator[tuple[TestClient, sessionmaker[Session], str]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with sessions() as session:
        qa_version_id = _seed_publishable_qa(session)
    app = create_app()

    def override_session() -> Iterator[Session]:
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        yield client, sessions, qa_version_id
    engine.dispose()


def test_workspace_lists_publishable_qa_and_registers_release(
    retest_client: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    client, _, qa_version_id = retest_client

    before = client.get("/api/retest-workspace")
    published = client.post(
        f"/api/qa-versions/{qa_version_id}/publish",
        json={"actor": "林乔", "release_note": "已同步到退款知识库"},
    )
    after = client.get("/api/retest-workspace")

    assert before.status_code == 200
    assert before.json()["summary"]["pending_publish_count"] == 1
    assert before.json()["pending_publish"][0]["qa_version_id"] == qa_version_id
    assert published.status_code == 200, published.text
    assert published.json()["workspace_state"] == "waiting_samples"
    payload = after.json()
    assert payload["summary"] == {
        "pending_publish_count": 0,
        "waiting_samples_count": 1,
        "ready_count": 0,
        "running_count": 0,
        "recovered_count": 0,
        "not_recovered_count": 0,
    }
    assert payload["items"][0]["published_by"] == "林乔"
    assert payload["items"][0]["release_note"] == "已同步到退款知识库"
    assert payload["items"][0]["replay_samples"] == {"available": 1, "required": 1}
    assert payload["items"][0]["new_samples"] == {"available": 0, "required": 1}
    assert payload["items"][0]["locked_rule"]["pass_rate_threshold"] == 0.8
    detail = client.get(f"/api/retest-workspace/{published.json()['retest_run_id']}")
    assert detail.status_code == 200
    assert detail.json()["explanation"]["verdict"] == "等待发布后新对话样本"
    assert detail.json()["samples"][0]["status"] == "pending"
    assert detail.json()["samples"][0]["evaluation"] is None
    assert detail.json()["samples"][0]["conversation"]["messages"]


def test_publishing_same_qa_is_idempotent_after_retest_completed(
    retest_client: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    client, sessions, qa_version_id = retest_client
    first = client.post(
        f"/api/qa-versions/{qa_version_id}/publish",
        json={"actor": "林乔", "release_note": "首次发布"},
    ).json()
    with sessions() as session:
        run = session.get(RetestRun, first["retest_run_id"])
        assert run is not None
        run.status = RetestStatus.RECOVERED
        session.commit()

    second = client.post(
        f"/api/qa-versions/{qa_version_id}/publish",
        json={"actor": "林乔", "release_note": "重复点击"},
    )

    assert second.status_code == 200, second.text
    assert second.json()["retest_run_id"] == first["retest_run_id"]
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(RetestRun)) == 1


def test_replay_sampling_deduplicates_same_conversation_across_evaluation_runs(
    retest_client: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    client, sessions, qa_version_id = retest_client
    with sessions() as session:
        original = session.scalar(select(EvaluationResult))
        source_run = session.scalar(select(EvaluationRun))
        alert = session.scalar(select(Alert))
        assert original is not None and source_run is not None and alert is not None
        duplicate_run = EvaluationRun(
            template_id=source_run.template_id,
            prompt_version_id=source_run.prompt_version_id,
            rule_version_id=source_run.rule_version_id,
            provider=source_run.provider,
            model=source_run.model,
            status=RunStatus.SUCCEEDED,
        )
        session.add(duplicate_run)
        session.flush()
        duplicate = EvaluationResult(
            run_id=duplicate_run.id,
            conversation_id=original.conversation_id,
            total_score=original.total_score,
            dimension_scores=original.dimension_scores,
            passed=False,
            reason=original.reason,
            evidence=original.evidence,
            confidence=Confidence.HIGH,
        )
        session.add(duplicate)
        session.flush()
        session.add(AlertResult(alert_id=alert.id, evaluation_result_id=duplicate.id))
        session.commit()

    published = client.post(
        f"/api/qa-versions/{qa_version_id}/publish",
        json={"actor": "林乔", "release_note": "发布完成"},
    )

    assert published.status_code == 200, published.text
    assert published.json()["sample_count"] == 1


def test_refresh_and_execute_strict_two_cohort_retest(
    retest_client: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    client, sessions, qa_version_id = retest_client
    transport = PassingRetestTransport()
    client.app.dependency_overrides[get_retest_provider] = lambda: EvaluationProvider(transport)
    published = client.post(
        f"/api/qa-versions/{qa_version_id}/publish",
        json={"actor": "林乔", "release_note": "发布完成"},
    ).json()
    run_id = published["retest_run_id"]

    waiting = client.post(f"/api/retests/{run_id}/execute", json={"actor": "林乔"})
    assert waiting.status_code == 422
    assert "新增样本" in waiting.json()["detail"]
    assert transport.calls == 0

    with sessions() as session:
        source = session.query(DataSource).one()
        session.add(
            Conversation(
                data_source_id=source.id,
                external_id="refund-after-release",
                scenario="退款进度查询",
                status="resolved",
                body={
                    "messages": [
                        {"role": "user", "content": "退款什么时候到账？"},
                        {"role": "assistant", "content": "通常 1 至 3 个工作日原路到账，可联系 13800138000。"},
                    ]
                },
                occurred_at=datetime.now(UTC),
                created_at=datetime.now(UTC) + timedelta(minutes=1),
            )
        )
        source_run = session.scalar(
            select(EvaluationRun)
            .where(EvaluationRun.status == RunStatus.SUCCEEDED)
            .order_by(EvaluationRun.created_at)
        )
        assert source_run is not None
        source_run.model = "后来修改的源模型"
        session.commit()

    refreshed = client.post(f"/api/retests/{run_id}/refresh-samples")
    executed = client.post(f"/api/retests/{run_id}/execute", json={"actor": "林乔"})
    detail = client.get(f"/api/retest-workspace/{run_id}")

    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["workspace_state"] == "ready"
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "recovered"
    assert executed.json()["replay_pass_rate"] == 1.0
    assert executed.json()["new_sample_pass_rate"] == 1.0
    assert transport.calls == 2
    assert detail.status_code == 200
    assert detail.json()["workspace_state"] == "recovered"
    assert detail.json()["locked_rule"]["prompt_version"] == "V1"
    assert detail.json()["locked_rule"]["model"] == "judge-v1"
    assert detail.json()["method"]["model"] == "judge-v1"
    assert detail.json()["method"]["sample_selection"] == {
        "replay": "关联问题中的历史失败对话",
        "new": "QA 发布后的同场景新对话",
    }
    assert detail.json()["explanation"]["formula"] == "历史回放和新对话两组通过率都达标"
    assert detail.json()["explanation"]["replay"] == {
        "passed": 1,
        "completed": 1,
        "total": 1,
        "pass_rate": 1.0,
    }
    assert detail.json()["explanation"]["new"] == {
        "passed": 1,
        "completed": 1,
        "total": 1,
        "pass_rate": 1.0,
    }
    assert len(detail.json()["samples"]) == 2
    transcript = str(detail.json()["samples"])
    assert "13800138000" not in transcript
    assert "[PHONE]" in transcript
    sample = detail.json()["samples"][0]
    assert sample["cohort"] in ("replay", "new")
    assert sample["conversation"]["messages"]
    assert sample["evaluation"]["total_score"] == 90.0
    assert sample["evaluation"]["dimension_scores"]["correctness"] == 90
    assert sample["evaluation"]["reason"] == "回复符合发布后的规则。"
    assert sample["evaluation"]["evidence"]
    assert sample["evaluation"]["confidence"] == "high"
    assert sample["evaluation"]["severe_factual_error"] is False
    assert sample["evaluation"]["severe_compliance_error"] is False
    calls_before_detail_refresh = transport.calls
    assert client.get(f"/api/retest-workspace/{run_id}").status_code == 200
    assert transport.calls == calls_before_detail_refresh

    with sessions() as session:
        sample_count = session.scalar(
            select(func.count()).select_from(RetestSample).where(
                RetestSample.retest_run_id == run_id
            )
        )
    terminal_refresh = client.post(f"/api/retests/{run_id}/refresh-samples")
    assert terminal_refresh.status_code == 422
    with sessions() as session:
        assert session.scalar(
            select(func.count()).select_from(RetestSample).where(
                RetestSample.retest_run_id == run_id
            )
        ) == sample_count


def test_failed_retest_resumes_without_charging_successful_samples_twice(
    retest_client: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    client, sessions, qa_version_id = retest_client
    published = client.post(
        f"/api/qa-versions/{qa_version_id}/publish",
        json={"actor": "林乔", "release_note": "发布完成"},
    ).json()
    run_id = published["retest_run_id"]
    with sessions() as session:
        source = session.query(DataSource).one()
        session.add(
            Conversation(
                data_source_id=source.id,
                external_id="refund-retry-new",
                scenario="退款进度查询",
                status="resolved",
                body={"messages": [{"role": "user", "content": "退款呢？"}, {"role": "assistant", "content": "1 至 3 个工作日到账。"}]},
                occurred_at=datetime.now(UTC) + timedelta(minutes=1),
                created_at=datetime.now(UTC) + timedelta(minutes=1),
            )
        )
        session.commit()

    failing = FailSecondRetestTransport()
    client.app.dependency_overrides[get_retest_provider] = lambda: EvaluationProvider(failing)
    failed = client.post(f"/api/retests/{run_id}/execute", json={"actor": "林乔"})
    assert failed.status_code == 502
    assert failing.calls == 2
    with sessions() as session:
        source_run = session.scalar(
            select(EvaluationRun)
            .where(EvaluationRun.status == RunStatus.SUCCEEDED)
            .order_by(EvaluationRun.created_at)
        )
        assert source_run is not None
        replacement_prompt = PromptVersion(
            name="被替换的 Prompt",
            version="V99",
            content="重试前被修改的 Prompt",
            published_at=datetime.now(UTC),
        )
        session.add(replacement_prompt)
        session.flush()
        source_run.model = "重试前被修改的源模型"
        source_run.prompt_version_id = replacement_prompt.id
        session.commit()

    resumed = PassingRetestTransport()
    client.app.dependency_overrides[get_retest_provider] = lambda: EvaluationProvider(resumed)
    completed = client.post(f"/api/retests/{run_id}/execute", json={"actor": "林乔"})

    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "recovered"
    assert resumed.calls == 1
    detail = client.get(f"/api/retest-workspace/{run_id}").json()
    assert detail["method"]["model"] == "judge-v1"
    assert detail["method"]["prompt"]["content"] == "请按公司规则评测。"


def test_stale_running_retest_can_resume_after_process_interruption(
    retest_client: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    client, sessions, qa_version_id = retest_client
    transport = PassingRetestTransport()
    client.app.dependency_overrides[get_retest_provider] = lambda: EvaluationProvider(transport)
    published = client.post(
        f"/api/qa-versions/{qa_version_id}/publish",
        json={"actor": "林乔", "release_note": "发布完成"},
    ).json()
    run_id = published["retest_run_id"]
    _add_new_conversation(sessions, "refund-stale-new")
    client.post(f"/api/retests/{run_id}/refresh-samples")
    with sessions() as session:
        run = session.get(RetestRun, run_id)
        assert run is not None
        run.status = RetestStatus.RUNNING
        run.started_at = datetime.now(UTC) - timedelta(minutes=31)
        session.commit()

    interrupted = client.get(f"/api/retest-workspace/{run_id}")
    assert interrupted.json()["workspace_state"] == "interrupted"

    resumed = client.post(f"/api/retests/{run_id}/execute", json={"actor": "林乔"})

    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "recovered"
    assert transport.calls == 2


def test_superseded_worker_cannot_persist_a_late_model_response(
    retest_client: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    client, sessions, qa_version_id = retest_client
    published = client.post(
        f"/api/qa-versions/{qa_version_id}/publish",
        json={"actor": "林乔", "release_note": "发布完成"},
    ).json()
    run_id = published["retest_run_id"]
    _add_new_conversation(sessions, "refund-superseded-new")
    client.post(f"/api/retests/{run_id}/refresh-samples")
    transport = SupersedingRetestTransport(sessions, run_id)
    client.app.dependency_overrides[get_retest_provider] = lambda: EvaluationProvider(transport)

    response = client.post(f"/api/retests/{run_id}/execute", json={"actor": "林乔"})

    assert response.status_code == 502
    assert "已由新的执行接管" in response.json()["detail"]
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(EvaluationResult)) == 1
        run = session.get(RetestRun, run_id)
        assert run is not None and run.status == RetestStatus.RUNNING


def test_complete_retest_is_not_exposed_as_a_public_shortcut(
    retest_client: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    client, sessions, qa_version_id = retest_client
    published = client.post(
        f"/api/qa-versions/{qa_version_id}/publish",
        json={"actor": "林乔", "release_note": "发布完成"},
    ).json()
    run_id = published["retest_run_id"]
    _add_new_conversation(sessions, "refund-partial-new-1")
    _add_new_conversation(sessions, "refund-partial-new-2")
    client.post(f"/api/retests/{run_id}/refresh-samples")
    with sessions() as session:
        run = session.get(RetestRun, run_id)
        source_run = session.scalar(select(EvaluationRun).where(EvaluationRun.status == RunStatus.SUCCEEDED))
        samples = list(
            session.scalars(
                select(RetestSample)
                .where(RetestSample.retest_run_id == run_id)
                .order_by(RetestSample.cohort)
            )
        )
        assert run is not None and source_run is not None and len(samples) == 3
        result_run = EvaluationRun(
            template_id=source_run.template_id,
            prompt_version_id=source_run.prompt_version_id,
            rule_version_id=source_run.rule_version_id,
            provider="test",
            model="judge-v1",
            status=RunStatus.RUNNING,
        )
        session.add(result_run)
        session.flush()
        for sample in (samples[0], samples[-1]):
            result = EvaluationResult(
                run_id=result_run.id,
                conversation_id=sample.conversation_id,
                total_score=Decimal(90),
                dimension_scores={"correctness": 90},
                passed=True,
                reason="通过",
                evidence=["有效回复"],
                confidence=Confidence.HIGH,
            )
            session.add(result)
            session.flush()
            sample.retest_evaluation_result_id = result.id
        run.status = RetestStatus.RUNNING
        session.commit()

    completed = client.post(f"/api/retests/{run_id}/complete", json={"actor": "林乔"})

    assert completed.status_code == 404


def _add_new_conversation(
    sessions: sessionmaker[Session], external_id: str
) -> None:
    with sessions() as session:
        source = session.query(DataSource).one()
        session.add(
            Conversation(
                data_source_id=source.id,
                external_id=external_id,
                scenario="退款进度查询",
                status="resolved",
                body={
                    "messages": [
                        {"role": "user", "content": "退款什么时候到账？"},
                        {"role": "assistant", "content": "1 至 3 个工作日到账。"},
                    ]
                },
                occurred_at=datetime.now(UTC) + timedelta(minutes=1),
                created_at=datetime.now(UTC) + timedelta(minutes=1),
            )
        )
        session.commit()


def _seed_publishable_qa(session: Session) -> str:
    now = datetime.now(UTC) - timedelta(days=1)
    source = DataSource(name="retest-workspace-source", kind="test")
    template = EvaluationTemplate(
        name="客服质量评测",
        version="V1",
        weights={
            "correctness": 0.2,
            "completeness": 0.2,
            "relevance": 0.2,
            "service_experience": 0.2,
            "compliance": 0.2,
        },
        threshold=Decimal(75),
        veto_rules={},
    )
    prompt = PromptVersion(
        name="客服质量评测 Prompt", version="V1", content="请按公司规则评测。", published_at=now
    )
    rule = RuleVersion(
        kind="客服复测规则",
        version="V1",
        config={
            "retest_replay_samples": 10,
            "retest_new_samples": 10,
            "retest_min_replay": 1,
            "retest_min_new": 1,
            "retest_pass_threshold": 0.8,
        },
    )
    run = EvaluationRun(
        template=template,
        prompt_version=prompt,
        rule_version=rule,
        provider="test",
        model="judge-v1",
        model_parameters={"temperature": 0},
        status=RunStatus.SUCCEEDED,
    )
    session.add_all((source, run))
    session.flush()
    conversation = Conversation(
        data_source_id=source.id,
        external_id="refund-before-release",
        scenario="退款进度查询",
        status="resolved",
        body={
            "messages": [
                {"role": "user", "content": "退款什么时候到账？"},
                {"role": "assistant", "content": "请稍后。"},
            ]
        },
        occurred_at=now,
        created_at=now,
    )
    session.add(conversation)
    session.flush()
    result = EvaluationResult(
        run_id=run.id,
        conversation_id=conversation.id,
        total_score=Decimal(30),
        dimension_scores={"completeness": 20},
        passed=False,
        reason="缺少退款到账时效",
        evidence=["请稍后。"],
        confidence=Confidence.HIGH,
    )
    session.add(result)
    session.flush()
    cluster = BadcaseCluster(
        run_id=run.id,
        scenario="退款进度查询",
        weakest_dimension="completeness",
        normalized_reason="缺少退款到账时效",
        algorithm_version="v1",
        grouping_key="retest-refund-demo",
    )
    alert = Alert(
        kind="pass_rate_drop",
        priority="P1",
        scenario="退款进度查询",
        root_cause=RootCause.MISSING_KNOWLEDGE,
        status=AlertStatus.AWAITING_FIX,
        merge_key="retest-refund-alert",
        baseline_value=Decimal("0.90"),
        current_value=Decimal("0.30"),
        impact_count=18,
        window_started_at=now,
        window_ended_at=now,
    )
    session.add_all((cluster, alert))
    session.flush()
    session.add_all(
        (
            ClusterMember(
                cluster_id=cluster.id,
                evaluation_result_id=result.id,
                representative_rank=1,
                confirmed_root_cause=RootCause.MISSING_KNOWLEDGE,
                confirmed_by="林乔",
                confirmed_at=now,
            ),
            AlertResult(alert_id=alert.id, evaluation_result_id=result.id),
        )
    )
    task = Task(
        type=TaskType.QA_REVIEW,
        status=TaskStatus.DONE,
        alert_id=alert.id,
        cluster_id=cluster.id,
        title="审核退款到账时效 QA",
        priority="P1",
        payload={},
        completed_at=now,
    )
    session.add(task)
    session.flush()
    draft = QADraft(
        cluster_id=cluster.id,
        task_id=task.id,
        status=QADraftStatus.APPROVED,
        current_version_number=1,
        confidence=Confidence.HIGH,
    )
    session.add(draft)
    session.flush()
    version = QAVersion(
        draft_id=draft.id,
        version_number=1,
        content={
            "question": "退款什么时候到账？",
            "answer": "退款审核通过后通常 1 至 3 个工作日原路到账。",
            "applicability": "退款审核通过",
            "handling_steps": ["查询退款状态", "告知到账时效"],
            "estimated_time": "1 至 3 个工作日",
            "escalation": "超时转人工",
        },
        created_by="模型",
        approved_by="林乔",
        approved_at=now,
    )
    session.add(version)
    session.commit()
    return version.id
