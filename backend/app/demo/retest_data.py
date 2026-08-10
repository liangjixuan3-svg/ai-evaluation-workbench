from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import Alert, AlertResult, Task
from app.analysis.models import BadcaseCluster, ClusterMember
from app.evaluation.models import (
    EvaluationResult,
    EvaluationRun,
    EvaluationTemplate,
    PromptVersion,
    RuleVersion,
)
from app.ingestion.models import Conversation, DataSource
from app.remediation.models import QADraft, QAVersion
from app.shared.enums import (
    AlertStatus,
    Confidence,
    QADraftStatus,
    RootCause,
    RunStatus,
    TaskStatus,
    TaskType,
)

DEMO_SOURCE_NAME = "发布复测工作台演示数据"
DEMO_PREFIX = "retest-demo-v2"


def _id(kind: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"ai-evaluation-workbench/{DEMO_PREFIX}/{kind}"))


def seed_retest_demo_data(
    session: Session, *, provider: str = "openai-compatible", model: str = "deepseek-chat"
) -> dict[str, int]:
    source = session.scalar(select(DataSource).where(DataSource.name == DEMO_SOURCE_NAME))
    if source is None:
        _create_demo_graph(session, provider, model)
        session.commit()
    from app.retest.service import retest_workspace

    pending = sum(
        item["qa_version_id"] == _id("qa-version")
        for item in retest_workspace(session)["pending_publish"]
    )
    return {"pending_publish_count": pending}


def _create_demo_graph(session: Session, provider: str, model: str) -> None:
    before = datetime(2026, 8, 9, 10, tzinfo=UTC)
    source = DataSource(
        id=_id("source"), name=DEMO_SOURCE_NAME, kind="demo", config={"marker": DEMO_PREFIX}
    )
    template = EvaluationTemplate(
        id=_id("template"),
        name="发布复测演示评测模板",
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
        id=_id("prompt"),
        name="发布复测演示 Prompt",
        version="V1",
        content="请按照客服质量规则评测回答是否准确、完整、相关、友好且合规。",
        published_at=before,
    )
    rule = RuleVersion(
        id=_id("rule"),
        kind="retest_demo",
        version="V1",
        config={
            "marker": DEMO_PREFIX,
            "retest_replay_samples": 10,
            "retest_new_samples": 10,
            "retest_min_replay": 1,
            "retest_min_new": 1,
            "retest_pass_threshold": 0.8,
        },
    )
    run = EvaluationRun(
        id=_id("source-run"),
        template=template,
        prompt_version=prompt,
        rule_version=rule,
        provider=provider,
        model=model,
        model_parameters={"temperature": 0},
        status=RunStatus.SUCCEEDED,
        succeeded_count=1,
        completed_at=before,
    )
    session.add_all((source, run))
    session.flush()
    old_conversation = Conversation(
        id=_id("old-conversation"),
        data_source_id=source.id,
        external_id=f"{DEMO_PREFIX}-old",
        scenario="破损件赔付咨询",
        status="escalated",
        body={
            "messages": [
                {"role": "user", "content": "收到的杯子碎了，应该怎么办？"},
                {"role": "assistant", "content": "请稍后。"},
            ]
        },
        occurred_at=before,
        created_at=before,
    )
    old_result = EvaluationResult(
        id=_id("old-result"),
        run_id=run.id,
        conversation=old_conversation,
        total_score=Decimal(35),
        dimension_scores={
            "correctness": 35,
            "completeness": 25,
            "relevance": 50,
            "service_experience": 30,
            "compliance": 60,
        },
        passed=False,
        reason="没有说明破损凭证、申请入口和处理时效。",
        evidence=["请稍后。"],
        confidence=Confidence.HIGH,
    )
    cluster = BadcaseCluster(
        id=_id("cluster"),
        run_id=run.id,
        scenario="破损件赔付咨询",
        weakest_dimension="completeness",
        normalized_reason="没有说明破损件赔付流程",
        algorithm_version="V1",
        grouping_key=DEMO_PREFIX,
        created_at=before,
    )
    alert = Alert(
        id=_id("alert"),
        kind="knowledge_gap",
        priority="P1",
        scenario="破损件赔付咨询",
        root_cause=RootCause.MISSING_KNOWLEDGE,
        status=AlertStatus.AWAITING_FIX,
        merge_key=DEMO_PREFIX,
        baseline_value=Decimal("0.86"),
        current_value=Decimal("0.35"),
        impact_count=24,
        window_started_at=before,
        window_ended_at=before,
    )
    session.add_all((old_conversation, old_result, cluster, alert))
    session.flush()
    session.add_all(
        (
            ClusterMember(
                cluster_id=cluster.id,
                evaluation_result_id=old_result.id,
                representative_rank=1,
                confirmed_root_cause=RootCause.MISSING_KNOWLEDGE,
                confirmed_by="演示运营员",
                confirmed_at=before,
            ),
            AlertResult(alert_id=alert.id, evaluation_result_id=old_result.id),
        )
    )
    task = Task(
        id=_id("task"),
        type=TaskType.QA_REVIEW,
        status=TaskStatus.DONE,
        alert_id=alert.id,
        cluster_id=cluster.id,
        title="补充破损件赔付流程",
        priority="P1",
        payload={"marker": DEMO_PREFIX},
        completed_at=before,
    )
    session.add(task)
    session.flush()
    draft = QADraft(
        id=_id("draft"),
        cluster_id=cluster.id,
        task_id=task.id,
        status=QADraftStatus.APPROVED,
        current_version_number=1,
        confidence=Confidence.HIGH,
        created_at=before,
    )
    version = QAVersion(
        id=_id("qa-version"),
        draft=draft,
        version_number=1,
        content={
            "question": "收到的商品破损怎么办？",
            "answer": "请在订单售后入口上传破损照片并申请赔付，通常 24 小时内审核。",
            "applicability": "签收后发现商品破损",
            "handling_steps": ["拍摄破损照片", "进入订单售后", "提交赔付申请"],
            "estimated_time": "24 小时内审核",
            "escalation": "超过 24 小时未处理时转人工",
        },
        created_by="演示运营员",
        approved_by="演示运营员",
        approved_at=before,
        created_at=before,
    )
    session.add_all((draft, version))
    session.add(
        Conversation(
            id=_id("new-conversation"),
            data_source_id=source.id,
            external_id=f"{DEMO_PREFIX}-new",
            scenario="破损件赔付咨询",
            status="resolved",
            body={
                "messages": [
                    {"role": "user", "content": "收到的杯子碎了，应该怎么办？"},
                    {
                        "role": "assistant",
                        "content": "请在订单售后入口上传破损照片并申请赔付，通常 24 小时内审核。",
                    },
                ]
            },
            occurred_at=datetime(2030, 1, 1, tzinfo=UTC),
            created_at=datetime(2030, 1, 1, tzinfo=UTC),
        )
    )
