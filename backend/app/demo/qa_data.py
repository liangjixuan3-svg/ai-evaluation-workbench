from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.alerts.models import Task
from app.analysis.models import BadcaseCluster, ClusterMember, RootCauseSuggestion
from app.evaluation.models import (
    EvaluationResult,
    EvaluationRun,
    EvaluationTemplate,
    PromptVersion,
    RuleVersion,
)
from app.ingestion.models import Conversation, DataSource
from app.remediation.models import (
    ExportRecord,
    QADraft,
    QAEvidence,
    QAExportItem,
    QAVersion,
)
from app.shared.audit import AuditEvent
from app.shared.enums import (
    Confidence,
    QADraftStatus,
    RootCause,
    RunStatus,
    TaskStatus,
    TaskType,
)

DEMO_SOURCE_NAME = "QA审核工作台演示数据"
DEMO_PREFIX = "qa-demo-"
DEMO_VERSION = "qa-demo-v1"
DEMO_NOW = datetime(2026, 8, 10, 10, tzinfo=UTC)

SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "key": "logistics",
        "scenario": "物流异常催单",
        "summary": "物流停滞后没有说明查询与升级流程",
        "user": "物流三天没更新了，能帮我催一下吗？手机号 13800138000",
        "assistant": "请稍后。",
        "score": 31,
        "priority": "P1",
        "state": "awaiting_generation",
        "content": None,
    },
    {
        "key": "refund",
        "scenario": "退款进度查询",
        "summary": "没有说明退款到账时间和超时处理方式",
        "user": "退款审核通过了，什么时候能到账？",
        "assistant": "退款已经在处理中，请耐心等待。",
        "score": 48,
        "priority": "P1",
        "state": "pending_review",
        "content": {
            "question": "退款审核通过后多久能到账？",
            "answer": "退款将原路退回，通常在审核通过后 1 至 3 个工作日到账。",
            "applicability": "退款状态为审核通过",
            "handling_steps": ["查询退款状态", "核对原支付渠道", "告知预计到账时间"],
            "estimated_time": "1 至 3 个工作日",
            "escalation": "超过 3 个工作日仍未到账时转人工核查",
        },
    },
    {
        "key": "invoice",
        "scenario": "发票开具咨询",
        "summary": "没有解释电子发票开具时效和获取入口",
        "user": "订单完成后在哪里开发票？",
        "assistant": "您可以稍后再看看。",
        "score": 43,
        "priority": "P2",
        "state": "approved",
        "content": {
            "question": "订单完成后如何申请电子发票？",
            "answer": "订单完成后可在订单详情页进入发票服务，提交抬头后申请电子发票。",
            "applicability": "支持开票且已完成的订单",
            "handling_steps": ["打开订单详情", "进入发票服务", "填写并确认发票抬头"],
            "estimated_time": "提交后 24 小时内",
            "escalation": "超过 24 小时未开具或订单无开票入口时转人工",
        },
        "business_evidence": {
            "source_ref": "电商发票管理规范 V2",
            "excerpt": "订单完成后，用户可从订单详情申请电子发票，通常在 24 小时内开具。",
        },
    },
    {
        "key": "product",
        "scenario": "商品信息咨询",
        "summary": "回答了未经制度确认的商品保修期限",
        "user": "这个商品保修几年？",
        "assistant": "所有商品都是全国联保三年。",
        "score": 25,
        "priority": "P2",
        "state": "rejected",
        "content": {
            "question": "平台商品统一保修几年？",
            "answer": "平台所有商品统一提供三年全国联保。",
            "applicability": "全部平台商品",
            "handling_steps": ["查询商品", "告知三年联保"],
            "estimated_time": "即时",
            "escalation": "用户不认可时转人工",
        },
        "rejection_reason": "不同品类和商家的保修规则不同，不能使用统一三年保修话术。",
    },
)


def _id(kind: str, key: str = "shared") -> str:
    return str(uuid5(NAMESPACE_URL, f"ai-evaluation-workbench/{DEMO_VERSION}/{kind}/{key}"))


def seed_qa_demo_data(session: Session) -> dict[str, int]:
    existing = session.scalar(select(DataSource).where(DataSource.name == DEMO_SOURCE_NAME))
    if existing is not None:
        return _summary(session)

    source = DataSource(
        id=_id("source"),
        name=DEMO_SOURCE_NAME,
        kind="demo",
        config={"marker": DEMO_VERSION},
    )
    template = EvaluationTemplate(
        id=_id("template"),
        name="QA 演示评测模板",
        version=DEMO_VERSION,
        weights={
            "correctness": 25,
            "completeness": 25,
            "relevance": 20,
            "service_experience": 15,
            "compliance": 15,
        },
        threshold=Decimal(75),
        veto_rules={},
    )
    prompt = PromptVersion(
        id=_id("prompt"),
        name="QA 演示评测 Prompt",
        version=DEMO_VERSION,
        content="演示评测 Prompt，不调用模型。",
        published_at=DEMO_NOW,
    )
    rule = RuleVersion(
        id=_id("rule"),
        kind="qa_demo",
        version=DEMO_VERSION,
        config={"marker": DEMO_VERSION},
    )
    run = EvaluationRun(
        id=_id("run"),
        template=template,
        prompt_version=prompt,
        rule_version=rule,
        provider="demo",
        model="deterministic-demo",
        model_parameters={"calls": 0},
        status=RunStatus.SUCCEEDED,
        succeeded_count=4,
        completed_at=DEMO_NOW,
    )
    session.add_all((source, run))
    session.flush()

    for index, item in enumerate(SCENARIOS, start=1):
        _add_scenario(session, source, run, item, index)
    session.commit()
    return _summary(session)


def _add_scenario(
    session: Session,
    source: DataSource,
    run: EvaluationRun,
    item: dict[str, Any],
    index: int,
) -> None:
    key = str(item["key"])
    occurred_at = DEMO_NOW.replace(hour=10 + index)
    conversation = Conversation(
        id=_id("conversation", key),
        data_source=source,
        external_id=f"{DEMO_PREFIX}{key}",
        scenario=item["scenario"],
        status="escalated",
        body={
            "messages": [
                {"role": "user", "content": item["user"]},
                {"role": "assistant", "content": item["assistant"]},
            ]
        },
        occurred_at=occurred_at,
    )
    result = EvaluationResult(
        id=_id("result", key),
        run=run,
        conversation=conversation,
        total_score=Decimal(str(item["score"])),
        dimension_scores={
            "correctness": item["score"],
            "completeness": max(int(item["score"]) - 10, 0),
            "relevance": 62,
            "service_experience": 55,
            "compliance": 70,
        },
        passed=False,
        reason=item["summary"],
        evidence=[item["assistant"]],
        confidence=Confidence.HIGH,
    )
    cluster = BadcaseCluster(
        id=_id("cluster", key),
        run_id=run.id,
        scenario=item["scenario"],
        weakest_dimension="completeness",
        normalized_reason=item["summary"],
        algorithm_version=DEMO_VERSION,
        grouping_key=f"{DEMO_PREFIX}{key}",
        created_at=occurred_at,
    )
    member = ClusterMember(
        cluster_id=cluster.id,
        evaluation_result_id=result.id,
        representative_rank=1,
        confirmed_root_cause=RootCause.MISSING_KNOWLEDGE,
        confirmed_by="演示运营员",
        confirmed_at=occurred_at,
    )
    suggestion = RootCauseSuggestion(
        id=_id("suggestion", key),
        cluster_id=cluster.id,
        evaluation_result_id=result.id,
        provider="demo",
        model="deterministic-demo",
        root_cause=RootCause.MISSING_KNOWLEDGE,
        reason=f"知识库缺少“{item['scenario']}”的明确处理规则。",
        evidence=[item["assistant"]],
        confidence=Confidence.HIGH,
        created_at=occurred_at,
    )
    task_status = {
        "awaiting_generation": TaskStatus.OPEN,
        "pending_review": TaskStatus.IN_PROGRESS,
        "approved": TaskStatus.DONE,
        "rejected": TaskStatus.CANCELLED,
    }[item["state"]]
    payload: dict[str, Any] = {
        "marker": DEMO_VERSION,
        "root_cause": RootCause.MISSING_KNOWLEDGE.value,
        "evidence": ["演示数据已人工确认知识缺失"],
    }
    if item.get("rejection_reason"):
        payload["qa_rejection_reason"] = item["rejection_reason"]
    task = Task(
        id=_id("task", key),
        type=TaskType.QA_REVIEW,
        status=task_status,
        cluster_id=cluster.id,
        title=f"补充{item['scenario']}知识",
        priority=item["priority"],
        payload=payload,
        completed_at=occurred_at if task_status in {TaskStatus.DONE, TaskStatus.CANCELLED} else None,
    )
    session.add_all((conversation, result, cluster))
    session.flush()
    session.add_all((member, suggestion, task))
    session.flush()

    if item["state"] != "awaiting_generation":
        _add_draft(session, item, key, cluster, task, occurred_at)


def _add_draft(
    session: Session,
    item: dict[str, Any],
    key: str,
    cluster: BadcaseCluster,
    task: Task,
    created_at: datetime,
) -> None:
    status = QADraftStatus(item["state"])
    current_version = 2 if status == QADraftStatus.APPROVED else 1
    draft = QADraft(
        id=_id("draft", key),
        cluster_id=cluster.id,
        task_id=task.id,
        status=status,
        current_version_number=current_version,
        confidence=Confidence.HIGH,
        created_at=created_at,
    )
    first = QAVersion(
        id=_id("version-1", key),
        draft=draft,
        version_number=1,
        content=item["content"],
        created_by="演示模型",
        created_at=created_at,
    )
    session.add_all((draft, first))
    if status == QADraftStatus.APPROVED:
        approved = QAVersion(
            id=_id("version-2", key),
            draft=draft,
            version_number=2,
            content=item["content"],
            created_by="演示运营员",
            approved_by="演示运营员",
            approved_at=created_at,
            created_at=created_at,
        )
        session.add(approved)
        session.flush()
        evidence = item["business_evidence"]
        session.add(
            QAEvidence(
                id=_id("business-evidence", key),
                qa_version_id=approved.id,
                source_type="business_reference",
                source_ref=evidence["source_ref"],
                excerpt=evidence["excerpt"],
                created_at=created_at,
            )
        )


def clear_qa_demo_data(session: Session) -> dict[str, int]:
    source = session.scalar(select(DataSource).where(DataSource.name == DEMO_SOURCE_NAME))
    if source is None:
        return {"task_count": 0}

    cluster_ids = list(
        session.scalars(
            select(BadcaseCluster.id).where(BadcaseCluster.grouping_key.like(f"{DEMO_PREFIX}%"))
        )
    )
    task_ids = list(session.scalars(select(Task.id).where(Task.cluster_id.in_(cluster_ids))))
    draft_ids = list(session.scalars(select(QADraft.id).where(QADraft.task_id.in_(task_ids))))
    version_ids = list(
        session.scalars(select(QAVersion.id).where(QAVersion.draft_id.in_(draft_ids)))
    )
    export_ids = list(
        session.scalars(select(QAExportItem.export_id).where(QAExportItem.qa_version_id.in_(version_ids)))
    )
    conversation_ids = list(
        session.scalars(select(Conversation.id).where(Conversation.data_source_id == source.id))
    )
    result_ids = list(
        session.scalars(
            select(EvaluationResult.id).where(EvaluationResult.conversation_id.in_(conversation_ids))
        )
    )

    session.execute(delete(QAExportItem).where(QAExportItem.qa_version_id.in_(version_ids)))
    session.execute(delete(QAEvidence).where(QAEvidence.qa_version_id.in_(version_ids)))
    session.execute(delete(QAVersion).where(QAVersion.id.in_(version_ids)))
    session.execute(delete(QADraft).where(QADraft.id.in_(draft_ids)))
    session.execute(delete(Task).where(Task.id.in_(task_ids)))
    session.execute(delete(RootCauseSuggestion).where(RootCauseSuggestion.cluster_id.in_(cluster_ids)))
    session.execute(delete(ClusterMember).where(ClusterMember.cluster_id.in_(cluster_ids)))
    session.execute(delete(BadcaseCluster).where(BadcaseCluster.id.in_(cluster_ids)))
    session.execute(delete(EvaluationResult).where(EvaluationResult.id.in_(result_ids)))
    session.execute(delete(Conversation).where(Conversation.id.in_(conversation_ids)))
    session.execute(delete(EvaluationRun).where(EvaluationRun.id == _id("run")))
    session.execute(delete(EvaluationTemplate).where(EvaluationTemplate.id == _id("template")))
    session.execute(delete(PromptVersion).where(PromptVersion.id == _id("prompt")))
    session.execute(delete(RuleVersion).where(RuleVersion.id == _id("rule")))
    session.execute(delete(DataSource).where(DataSource.id == source.id))
    entity_ids = task_ids + draft_ids + version_ids + cluster_ids + result_ids
    session.execute(delete(AuditEvent).where(AuditEvent.entity_id.in_(entity_ids)))
    for export_id in set(export_ids):
        remaining = session.scalar(
            select(func.count()).select_from(QAExportItem).where(QAExportItem.export_id == export_id)
        )
        if not remaining:
            session.execute(delete(ExportRecord).where(ExportRecord.id == export_id))
    session.commit()
    return {"task_count": len(task_ids)}


def _summary(session: Session) -> dict[str, int]:
    task_count = session.scalar(
        select(func.count())
        .select_from(Task)
        .join(BadcaseCluster, Task.cluster_id == BadcaseCluster.id)
        .where(BadcaseCluster.grouping_key.like(f"{DEMO_PREFIX}%"))
    )
    return {"task_count": task_count or 0}
