from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.rules import AlertSignal
from app.alerts.service import merge_alert
from app.analysis.service import cluster_badcases, persist_clusters
from app.evaluation.models import (
    EvaluationResult,
    EvaluationRun,
    EvaluationTemplate,
    PromptVersion,
    RuleVersion,
)
from app.evaluation.openai_compatible import EVALUATION_SYSTEM_PROMPT
from app.evaluation.providers import EvaluationProvider
from app.imports.models import ImportSession
from app.ingestion.contracts import SampleCandidate
from app.ingestion.models import (
    Conversation,
    SamplingBatch,
    SamplingBatchConversation,
)
from app.ingestion.sampling import SamplingPolicy, select_sample
from app.jobs.models import Job
from app.jobs.repository import enqueue_job
from app.shared.audit import record_audit
from app.shared.enums import RunStatus
from app.shared.types import utc_now

Strategy = Literal["random", "risk_first", "scenario_weighted"]
DIMENSIONS = (
    "correctness",
    "completeness",
    "relevance",
    "service_experience",
    "compliance",
)


@dataclass(frozen=True, slots=True)
class StartEvaluation:
    import_id: str
    sample_size: int
    strategy: Strategy
    threshold: float
    seed: int
    actor: str = "operator"


def create_evaluation_operation(
    session: Session, command: StartEvaluation, provider: EvaluationProvider
) -> EvaluationRun:
    imported = session.get(ImportSession, command.import_id)
    if imported is None or imported.status != "confirmed" or not imported.confirmed_source_id:
        raise ValueError("请选择已确认入库的数据批次")
    available = list(
        session.scalars(
            select(Conversation)
            .where(Conversation.data_source_id == imported.confirmed_source_id)
            .order_by(Conversation.id)
        )
    )
    if command.sample_size < 1 or command.sample_size > len(available):
        raise ValueError(f"抽样数量必须在 1 到 {len(available)} 之间")
    if command.threshold < 0 or command.threshold > 100:
        raise ValueError("通过阈值必须在 0 到 100 之间")
    operation_key = _operation_key(command, provider.identity.model)
    existing = session.scalar(
        select(EvaluationRun)
        .join(SamplingBatch, SamplingBatch.id == EvaluationRun.sampling_batch_id)
        .where(SamplingBatch.policy_version == operation_key)
    )
    if existing is not None:
        return existing
    template = _template(session, command.threshold)
    prompt = _prompt(session)
    rule = _rule(session)
    candidates = [
        SampleCandidate(
            id=UUID(conversation.id),
            scenario=conversation.scenario,
            is_risk=_is_risk(conversation),
        )
        for conversation in available
    ]
    selected_ids = select_sample(candidates, _policy(command), command.seed)
    now = utc_now()
    batch = SamplingBatch(
        policy_version=operation_key,
        seed=command.seed,
        status=RunStatus.SUCCEEDED,
        selected_count=len(selected_ids),
        started_at=now,
        completed_at=now,
    )
    session.add(batch)
    session.flush()
    session.add_all(
        SamplingBatchConversation(
            batch_id=batch.id,
            conversation_id=str(conversation_id),
            selection_reason=command.strategy,
        )
        for conversation_id in selected_ids
    )
    run = EvaluationRun(
        sampling_batch_id=batch.id,
        template_id=template.id,
        prompt_version_id=prompt.id,
        rule_version_id=rule.id,
        provider=provider.identity.provider,
        model=provider.identity.model,
        model_parameters={"temperature": 0},
    )
    session.add(run)
    session.flush()
    record_audit(
        session,
        actor=command.actor,
        action="evaluation_operation_created",
        entity_type="evaluation_run",
        entity_id=run.id,
        payload={
            "import_id": command.import_id,
            "sample_size": len(selected_ids),
            "strategy": command.strategy,
            "threshold": command.threshold,
            "model": provider.identity.model,
        },
    )
    enqueue_job(session, "evaluation_batch", {"run_id": run.id}, f"evaluation-batch:{run.id}")
    return run


def postprocess_evaluation(session: Session, run_id: str) -> None:
    results = list(
        session.scalars(
            select(EvaluationResult)
            .where(EvaluationResult.run_id == run_id)
            .order_by(EvaluationResult.created_at)
        )
    )
    clusters = persist_clusters(session, cluster_badcases(results))
    del clusters
    failed = [result for result in results if not result.passed]
    by_scenario: dict[str | None, list[EvaluationResult]] = {}
    for result in failed:
        by_scenario.setdefault(result.conversation.scenario, []).append(result)
    for scenario, scenario_results in by_scenario.items():
        scenario_total = sum(result.conversation.scenario == scenario for result in results)
        created_times = [result.created_at for result in scenario_results]
        merge_alert(
            session,
            AlertSignal(
                kind="issue_spike",
                priority="P1" if len(scenario_results) / scenario_total >= 0.3 else "P2",
                scenario=scenario,
                root_cause=None,
                baseline_value=0.0,
                current_value=len(scenario_results) / scenario_total,
                impact_count=len(scenario_results),
                result_ids=tuple(result.id for result in scenario_results),
                window_started_at=min(created_times),
                window_ended_at=max(created_times),
                merge_window=timedelta(hours=24),
            ),
        )


def operation_detail(session: Session, run_id: str) -> dict[str, Any]:
    run = session.get(EvaluationRun, run_id)
    if run is None:
        raise LookupError("评测运行不存在")
    results = list(
        session.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run_id))
    )
    sample_count = run.sampling_batch.selected_count if run.sampling_batch else 0
    passed_count = sum(result.passed for result in results)
    dimension_averages = {
        dimension: round(
            sum(float(result.dimension_scores[dimension]) for result in results) / len(results),
            2,
        )
        for dimension in DIMENSIONS
        if results and all(dimension in result.dimension_scores for result in results)
    }
    latest_error = session.scalar(
        select(Job.last_error)
        .where(Job.idempotency_key.like(f"evaluation-item:{run_id}:%"), Job.last_error.is_not(None))
        .order_by(Job.updated_at.desc())
    )
    return {
        "run_id": run.id,
        "stage": _stage(run.status),
        "sample_count": sample_count,
        "completed_count": len(results),
        "passed_count": passed_count,
        "failed_count": max(run.failed_count, len(results) - passed_count),
        "retrying_count": max(sample_count - len(results) - run.failed_count, 0),
        "pass_rate": round(passed_count / len(results), 4) if results else None,
        "average_score": (
            round(sum(float(result.total_score) for result in results) / len(results), 2)
            if results
            else None
        ),
        "dimension_averages": dimension_averages,
        "latest_error": latest_error,
        "model": run.model,
        "status": run.status.value,
        "created_at": run.created_at.isoformat(),
    }


def operation_results(
    session: Session, run_id: str, offset: int, limit: int
) -> dict[str, Any]:
    if session.get(EvaluationRun, run_id) is None:
        raise LookupError("评测运行不存在")
    total = int(
        session.scalar(
            select(func.count(EvaluationResult.id)).where(EvaluationResult.run_id == run_id)
        )
        or 0
    )
    rows = list(
        session.scalars(
            select(EvaluationResult)
            .where(EvaluationResult.run_id == run_id)
            .order_by(EvaluationResult.created_at, EvaluationResult.id)
            .offset(offset)
            .limit(limit)
        )
    )
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "id": result.id,
                "conversation_id": result.conversation_id,
                "scenario": result.conversation.scenario,
                "score": float(result.total_score),
                "passed": result.passed,
                "dimensions": result.dimension_scores,
                "reason": result.reason,
                "evidence": result.evidence,
                "confidence": result.confidence.value,
            }
            for result in rows
        ],
    }


def _template(session: Session, threshold: float) -> EvaluationTemplate:
    version = f"v1-t{threshold:g}"
    record = session.scalar(
        select(EvaluationTemplate).where(
            EvaluationTemplate.name == "customer-support-quality",
            EvaluationTemplate.version == version,
        )
    )
    if record is None:
        record = EvaluationTemplate(
            name="customer-support-quality",
            version=version,
            weights={dimension: 0.2 for dimension in DIMENSIONS},
            threshold=Decimal(str(threshold)),
            veto_rules={"severe_factual_error": True, "severe_compliance_error": True},
        )
        session.add(record)
        session.flush()
    return record


def _prompt(session: Session) -> PromptVersion:
    record = session.scalar(
        select(PromptVersion).where(
            PromptVersion.name == "customer-support-judge", PromptVersion.version == "v1"
        )
    )
    if record is None:
        record = PromptVersion(
            name="customer-support-judge", version="v1", content=EVALUATION_SYSTEM_PROMPT
        )
        session.add(record)
        session.flush()
    return record


def _rule(session: Session) -> RuleVersion:
    record = session.scalar(
        select(RuleVersion).where(
            RuleVersion.kind == "evaluation-operation", RuleVersion.version == "v1"
        )
    )
    if record is None:
        record = RuleVersion(
            kind="evaluation-operation",
            version="v1",
            config={"merge_window_hours": 24, "minimum_alert_samples": 1},
        )
        session.add(record)
        session.flush()
    return record


def _policy(command: StartEvaluation) -> SamplingPolicy:
    ratios = {
        "random": (1.0, 0.0, 0.0),
        "risk_first": (0.3, 0.2, 0.5),
        "scenario_weighted": (0.3, 0.5, 0.2),
    }[command.strategy]
    return SamplingPolicy(
        daily_budget=command.sample_size,
        random_ratio=ratios[0],
        scenario_ratio=ratios[1],
        risk_ratio=ratios[2],
        priority_scenarios=frozenset({"refund", "退款进度", "物流异常", "complaint"}),
    )


def _is_risk(conversation: Conversation) -> bool:
    return (conversation.status or "").casefold() in {
        "escalated",
        "negative_feedback",
        "complaint",
    }


def _operation_key(command: StartEvaluation, model: str) -> str:
    encoded = json.dumps(
        {
            "import": command.import_id,
            "size": command.sample_size,
            "strategy": command.strategy,
            "threshold": command.threshold,
            "seed": command.seed,
            "model": model,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"operation-{sha256(encoded.encode()).hexdigest()[:54]}"


def _stage(status: RunStatus) -> str:
    return {
        RunStatus.QUEUED: "queued",
        RunStatus.RUNNING: "evaluating",
        RunStatus.SUCCEEDED: "completed",
        RunStatus.PARTIAL: "partial",
        RunStatus.FAILED: "partial",
        RunStatus.MANUAL_REVIEW: "manual_review",
    }[status]
