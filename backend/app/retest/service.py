from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.alerts.models import Alert, AlertResult, Task
from app.analysis.models import BadcaseCluster, ClusterMember
from app.evaluation.contracts import EvaluationRequest
from app.evaluation.models import EvaluationResult, EvaluationRun, RuleVersion
from app.evaluation.providers import EvaluationProvider
from app.evaluation.scoring import calculate_outcome
from app.ingestion.models import Conversation
from app.ingestion.redaction import redact_conversation
from app.remediation.models import QADraft, QAVersion
from app.retest.models import RetestRun, RetestSample
from app.shared.audit import AuditEvent, record_audit
from app.shared.enums import (
    AlertStatus,
    Confidence,
    QADraftStatus,
    RetestCohort,
    RetestStatus,
    RunStatus,
    TaskStatus,
    TaskType,
)
from app.shared.types import new_uuid, utc_now


class InvalidRetestState(ValueError):
    pass


class RetestExecutionError(RuntimeError):
    pass


class RetestExecutionSuperseded(RuntimeError):
    pass


STALE_RETEST_AFTER = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class RetestDecision:
    replay_pass_rate: float
    new_sample_pass_rate: float
    recovered: bool


def decide_retest(
    *,
    replay_passed: int,
    replay_total: int,
    new_passed: int,
    new_total: int,
    threshold: float,
    min_replay: int,
    min_new: int,
) -> RetestDecision:
    if replay_total < min_replay or new_total < min_new:
        raise InvalidRetestState("复测样本不足，不能关闭告警")
    replay_rate = replay_passed / replay_total
    new_rate = new_passed / new_total
    return RetestDecision(
        replay_pass_rate=replay_rate,
        new_sample_pass_rate=new_rate,
        recovered=replay_rate >= threshold and new_rate >= threshold,
    )


def mark_published(
    session: Session, qa_version_id: str, actor: str, release_note: str = ""
) -> RetestRun:
    if not actor.strip():
        raise InvalidRetestState("actor is required")
    version = session.scalar(
        select(QAVersion).where(QAVersion.id == qa_version_id).with_for_update()
    )
    if version is None or version.approved_at is None:
        raise InvalidRetestState("只有已审核 QA 版本可以发布")
    draft = session.get(QADraft, version.draft_id)
    if draft is None:
        raise LookupError("QA draft does not exist")
    cluster = session.get(BadcaseCluster, draft.cluster_id)
    if cluster is None:
        raise LookupError("badcase cluster does not exist")
    run = session.get(EvaluationRun, cluster.run_id)
    if run is None:
        raise LookupError("evaluation run does not exist")
    alert = _cluster_alert(session, cluster.id)
    if alert is None:
        raise InvalidRetestState("聚类尚未关联告警")
    existing = session.scalar(
        select(RetestRun).where(
            RetestRun.alert_id == alert.id,
            RetestRun.qa_version_id == version.id,
        )
    )
    if existing is not None:
        return existing
    retest = RetestRun(
        id=new_uuid(),
        alert_id=alert.id,
        qa_version_id=version.id,
        rule_version_id=run.rule_version_id,
        status=RetestStatus.QUEUED,
        before_pass_rate=alert.current_value,
    )
    session.add(retest)
    method_run = _copy_evaluation_run(session, run, RunStatus.QUEUED)
    alert.status = AlertStatus.AWAITING_RETEST
    source_task = session.get(Task, draft.task_id) if draft.task_id else None
    if source_task is not None:
        source_task.status = TaskStatus.DONE
        source_task.completed_at = utc_now()
    retest_task = session.scalar(
        select(Task).where(Task.cluster_id == cluster.id, Task.type == TaskType.RETEST)
    )
    if retest_task is None:
        retest_task = Task(
            type=TaskType.RETEST,
            alert_id=alert.id,
            cluster_id=cluster.id,
            title=f"验证 {alert.scenario or '客服场景'} 修复效果",
            priority=alert.priority,
            payload={"retest_run_id": retest.id, "qa_version_id": version.id},
        )
        session.add(retest_task)
    record_audit(
        session,
        actor=actor,
        action="qa_published",
        entity_type="retest_run",
        entity_id=retest.id,
        payload={
            "qa_version_id": version.id,
            "alert_id": alert.id,
            "release_note": release_note.strip(),
            "evaluation_run_id": method_run.id,
        },
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(RetestRun).where(
                RetestRun.alert_id == alert.id,
                RetestRun.qa_version_id == version.id,
            )
        )
        if existing is None:
            raise
        return existing
    return retest


def build_retest_sample(session: Session, run_id: str) -> list[RetestSample]:
    retest = session.scalar(
        select(RetestRun)
        .where(RetestRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if retest is None:
        raise LookupError("retest run does not exist")
    if retest.status != RetestStatus.QUEUED:
        raise InvalidRetestState("只有等待中的复测任务可以刷新样本")
    existing = list(
        session.scalars(select(RetestSample).where(RetestSample.retest_run_id == run_id))
    )
    alert = session.get(Alert, retest.alert_id)
    rule = session.get(RuleVersion, retest.rule_version_id)
    if alert is None or rule is None:
        raise LookupError("retest lineage is incomplete")
    replay_limit = int(rule.config.get("retest_replay_samples", 20))
    new_limit = int(rule.config.get("retest_new_samples", 20))
    source_results = list(
        session.scalars(
            select(EvaluationResult)
            .join(AlertResult, AlertResult.evaluation_result_id == EvaluationResult.id)
            .where(AlertResult.alert_id == alert.id)
            .order_by(EvaluationResult.created_at.desc())
            .limit(replay_limit)
        )
    )
    existing_keys = {(sample.conversation_id, sample.cohort) for sample in existing}
    replay_remaining = max(
        replay_limit - sum(sample.cohort == RetestCohort.REPLAY for sample in existing), 0
    )
    replay_candidates = []
    seen_replay_ids = {
        conversation_id
        for conversation_id, cohort in existing_keys
        if cohort == RetestCohort.REPLAY
    }
    for result in source_results:
        if result.conversation_id in seen_replay_ids:
            continue
        seen_replay_ids.add(result.conversation_id)
        replay_candidates.append(
            RetestSample(
                retest_run_id=retest.id,
                conversation_id=result.conversation_id,
                cohort=RetestCohort.REPLAY,
                source_evaluation_result_id=result.id,
            )
        )
    samples = replay_candidates[:replay_remaining]
    replay_conversation_ids = {
        sample.conversation_id
        for sample in (*existing, *samples)
        if sample.cohort == RetestCohort.REPLAY
    }
    new_remaining = max(
        new_limit - sum(sample.cohort == RetestCohort.NEW for sample in existing), 0
    )
    new_conversations = list(
        session.scalars(
            select(Conversation)
            .where(
                Conversation.scenario == alert.scenario,
                Conversation.occurred_at >= retest.created_at,
                Conversation.id.not_in(replay_conversation_ids),
            )
            .order_by(Conversation.occurred_at.desc())
            .limit(new_limit)
        )
    )
    new_candidates = [
        RetestSample(
            retest_run_id=retest.id,
            conversation_id=conversation.id,
            cohort=RetestCohort.NEW,
        )
        for conversation in new_conversations
        if (conversation.id, RetestCohort.NEW) not in existing_keys
    ]
    samples.extend(new_candidates[:new_remaining])
    session.add_all(samples)
    session.commit()
    return list(
        session.scalars(
            select(RetestSample)
            .where(RetestSample.retest_run_id == run_id)
            .order_by(RetestSample.cohort, RetestSample.conversation_id)
        )
    )


def retest_workspace(session: Session) -> dict:
    pending_publish = _pending_publish_items(session)
    items = [_retest_item(session, run) for run in session.scalars(select(RetestRun))]
    summary = {
        "pending_publish_count": len(pending_publish),
        "waiting_samples_count": sum(item["workspace_state"] == "waiting_samples" for item in items),
        "ready_count": sum(item["workspace_state"] == "ready" for item in items),
        "running_count": sum(
            item["workspace_state"] in ("running", "interrupted") for item in items
        ),
        "recovered_count": sum(item["workspace_state"] == "recovered" for item in items),
        "not_recovered_count": sum(
            item["workspace_state"] == "not_recovered" for item in items
        ),
    }
    return {
        "summary": summary,
        "pending_publish": pending_publish,
        "items": sorted(items, key=lambda item: item["published_at"], reverse=True),
    }


def retest_workspace_detail(session: Session, run_id: str) -> dict:
    run = session.get(RetestRun, run_id)
    if run is None:
        raise LookupError("复测任务不存在")
    return _retest_item(session, run)


def execute_retest(
    session: Session, run_id: str, actor: str, provider: EvaluationProvider
) -> RetestRun:
    if not actor.strip():
        raise InvalidRetestState("操作人不能为空")
    current = session.scalar(
        select(RetestRun)
        .where(RetestRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if current is None:
        raise LookupError("复测任务不存在")
    if current.status in (
        RetestStatus.RECOVERED,
        RetestStatus.NOT_RECOVERED,
        RetestStatus.FAILED,
    ):
        return current
    if current.status == RetestStatus.RUNNING:
        if not _is_stale_running(current):
            raise InvalidRetestState("复测正在执行，请勿重复启动")
        current.status = RetestStatus.QUEUED
        current.execution_token = None
        record_audit(
            session,
            actor=actor,
            action="retest_execution_resumed",
            entity_type="retest_run",
            entity_id=current.id,
            payload={"reason": "运行超过 30 分钟未更新，按中断任务恢复"},
        )
        session.commit()
    samples = build_retest_sample(session, run_id)
    retest = session.scalar(
        select(RetestRun)
        .where(RetestRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if retest is None:
        raise LookupError("复测任务不存在")
    if retest.status == RetestStatus.RUNNING:
        raise InvalidRetestState("复测正在执行，请勿重复启动")
    if retest.status != RetestStatus.QUEUED:
        return retest
    rule = session.get(RuleVersion, retest.rule_version_id)
    method_run = retest_method_run(session, retest, samples)
    if rule is None or method_run is None:
        raise LookupError("复测任务缺少原评测版本信息")
    replay = [sample for sample in samples if sample.cohort == RetestCohort.REPLAY]
    fresh = [sample for sample in samples if sample.cohort == RetestCohort.NEW]
    min_replay = int(rule.config.get("retest_min_replay", 1))
    min_new = int(rule.config.get("retest_min_new", 1))
    if len(replay) < min_replay:
        raise InvalidRetestState(f"历史回放样本不足：需要 {min_replay} 条")
    if len(fresh) < min_new:
        raise InvalidRetestState(f"新增样本不足：需要 {min_new} 条")
    if provider.identity.provider != method_run.provider or provider.identity.model != method_run.model:
        raise InvalidRetestState("当前模型与原评测模型不一致，无法进行可比复测")

    retest.status = RetestStatus.RUNNING
    retest.started_at = retest.started_at or utc_now()
    execution_token = new_uuid()
    retest.execution_token = execution_token
    evaluation_run = _retest_evaluation_run(session, retest, samples, method_run)
    session.commit()
    try:
        for sample in samples:
            if sample.retest_evaluation_result_id is not None:
                continue
            conversation = session.get(Conversation, sample.conversation_id)
            if conversation is None:
                raise LookupError("复测样本对应的对话不存在")
            request = EvaluationRequest(
                conversation=redact_conversation(conversation),
                criteria=dict(rule.config.get("quality_standard", {})),
                instructions=evaluation_run.prompt_version.content,
            )
            retest.started_at = utc_now()
            session.commit()
            result = provider.evaluate(request)
            session.expire_all()
            current_retest = session.scalar(
                select(RetestRun)
                .where(RetestRun.id == run_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                current_retest is None
                or current_retest.status != RetestStatus.RUNNING
                or current_retest.execution_token != execution_token
            ):
                raise RetestExecutionSuperseded(
                    "复测已由新的执行接管，旧请求结果已丢弃"
                )
            retest = current_retest
            outcome = calculate_outcome(result, evaluation_run.template)
            persisted = EvaluationResult(
                run_id=evaluation_run.id,
                conversation_id=conversation.id,
                total_score=Decimal(str(outcome.score)),
                dimension_scores=result.dimensions,
                passed=outcome.passed,
                reason=result.reason,
                evidence=result.evidence,
                confidence=_confidence(result.confidence),
                severe_factual_error=result.severe_factual_error,
                severe_compliance_error=result.severe_compliance_error,
            )
            session.add(persisted)
            session.flush()
            sample.retest_evaluation_result_id = persisted.id
            evaluation_run.succeeded_count += 1
            session.commit()
    except RetestExecutionSuperseded as error:
        session.rollback()
        raise RetestExecutionError(str(error)) from error
    except Exception as error:
        session.rollback()
        _mark_retest_retryable(
            session,
            retest.id,
            evaluation_run.id,
            actor,
            error,
            execution_token,
        )
        raise RetestExecutionError(f"复测请求失败，可直接重试：{error}") from error
    evaluation_run.status = RunStatus.SUCCEEDED
    evaluation_run.completed_at = utc_now()
    record_audit(
        session,
        actor=actor,
        action="retest_evaluation_executed",
        entity_type="retest_run",
        entity_id=retest.id,
        payload={"evaluation_run_id": evaluation_run.id, "sample_count": len(samples)},
    )
    session.commit()
    try:
        return complete_retest(session, run_id, actor, execution_token)
    except RetestExecutionSuperseded as error:
        raise RetestExecutionError(str(error)) from error


def _retest_evaluation_run(
    session: Session,
    retest: RetestRun,
    samples: list[RetestSample],
    method_run: EvaluationRun,
) -> EvaluationRun:
    existing_result_id = next(
        (
            sample.retest_evaluation_result_id
            for sample in samples
            if sample.retest_evaluation_result_id is not None
        ),
        None,
    )
    if existing_result_id is not None:
        result = session.get(EvaluationResult, existing_result_id)
        run = session.get(EvaluationRun, result.run_id) if result else None
        if run is None:
            raise LookupError("复测结果缺少评测运行记录")
        run.status = RunStatus.RUNNING
        return run
    run = _planned_retest_evaluation_run(session, retest.id)
    if run is None:
        run = _copy_evaluation_run(session, method_run, RunStatus.RUNNING)
    run.status = RunStatus.RUNNING
    run.started_at = run.started_at or utc_now()
    return run


def _mark_retest_retryable(
    session: Session,
    retest_id: str,
    evaluation_run_id: str,
    actor: str,
    error: Exception,
    execution_token: str,
) -> None:
    retest = session.scalar(
        select(RetestRun)
        .where(RetestRun.id == retest_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    evaluation_run = session.get(EvaluationRun, evaluation_run_id)
    if retest is None or evaluation_run is None:
        raise LookupError("复测失败状态无法保存")
    if retest.execution_token != execution_token:
        return
    retest.status = RetestStatus.QUEUED
    retest.execution_token = None
    evaluation_run.status = (
        RunStatus.PARTIAL if evaluation_run.succeeded_count else RunStatus.FAILED
    )
    evaluation_run.completed_at = utc_now()
    record_audit(
        session,
        actor=actor,
        action="retest_evaluation_failed",
        entity_type="retest_run",
        entity_id=retest.id,
        payload={"evaluation_run_id": evaluation_run.id, "error": str(error)},
    )
    session.commit()


def complete_retest(
    session: Session, run_id: str, actor: str, execution_token: str
) -> RetestRun:
    retest = session.scalar(select(RetestRun).where(RetestRun.id == run_id).with_for_update())
    if retest is None:
        raise LookupError("retest run does not exist")
    if retest.execution_token != execution_token:
        raise RetestExecutionSuperseded("复测已由新的执行接管，旧执行不能结束任务")
    if retest.status != RetestStatus.RUNNING:
        raise InvalidRetestState("retest run is already complete")
    rule = session.get(RuleVersion, retest.rule_version_id)
    alert = session.get(Alert, retest.alert_id)
    if rule is None or alert is None:
        raise LookupError("retest lineage is incomplete")
    rows = list(
        session.execute(
            select(RetestSample.cohort, EvaluationResult.passed)
            .join(
                EvaluationResult,
                EvaluationResult.id == RetestSample.retest_evaluation_result_id,
            )
            .where(RetestSample.retest_run_id == run_id)
        )
    )
    sample_count = session.scalar(
        select(func.count())
        .select_from(RetestSample)
        .where(RetestSample.retest_run_id == run_id)
    )
    if len(rows) != sample_count:
        raise InvalidRetestState("仍有复测样本尚未完成，不能提前结束")
    replay = [passed for cohort, passed in rows if cohort == RetestCohort.REPLAY]
    fresh = [passed for cohort, passed in rows if cohort == RetestCohort.NEW]
    decision = decide_retest(
        replay_passed=sum(replay),
        replay_total=len(replay),
        new_passed=sum(fresh),
        new_total=len(fresh),
        threshold=float(rule.config.get("retest_pass_threshold", 0.8)),
        min_replay=int(rule.config.get("retest_min_replay", 1)),
        min_new=int(rule.config.get("retest_min_new", 1)),
    )
    retest.replay_pass_rate = Decimal(str(decision.replay_pass_rate))
    retest.new_sample_pass_rate = Decimal(str(decision.new_sample_pass_rate))
    retest.completed_at = utc_now()
    retest.execution_token = None
    retest.status = RetestStatus.RECOVERED if decision.recovered else RetestStatus.NOT_RECOVERED
    alert.status = AlertStatus.RECOVERED if decision.recovered else AlertStatus.NOT_RECOVERED
    task = session.scalar(
        select(Task).where(Task.alert_id == alert.id, Task.type == TaskType.RETEST)
    )
    if task is not None:
        task.status = TaskStatus.DONE if decision.recovered else TaskStatus.OPEN
        task.completed_at = utc_now() if decision.recovered else None
    record_audit(
        session,
        actor=actor,
        action="retest_completed",
        entity_type="retest_run",
        entity_id=retest.id,
        payload={
            "recovered": decision.recovered,
            "replay_pass_rate": decision.replay_pass_rate,
            "new_sample_pass_rate": decision.new_sample_pass_rate,
        },
    )
    session.commit()
    return retest


def close_false_positive(session: Session, alert_id: str, actor: str, reason: str) -> Alert:
    if not actor.strip() or not reason.strip():
        raise InvalidRetestState("误报关闭必须填写操作人和原因")
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise LookupError("alert does not exist")
    alert.status = AlertStatus.FALSE_POSITIVE
    record_audit(
        session,
        actor=actor,
        action="alert_closed_false_positive",
        entity_type="alert",
        entity_id=alert.id,
        payload={"reason": reason.strip()},
    )
    session.commit()
    return alert


def _cluster_alert(session: Session, cluster_id: str) -> Alert | None:
    return session.scalar(
        select(Alert)
        .join(AlertResult, AlertResult.alert_id == Alert.id)
        .join(ClusterMember, ClusterMember.evaluation_result_id == AlertResult.evaluation_result_id)
        .where(ClusterMember.cluster_id == cluster_id)
        .order_by(Alert.created_at.desc())
    )


def _pending_publish_items(session: Session) -> list[dict]:
    published_ids = set(session.scalars(select(RetestRun.qa_version_id)))
    versions = list(
        session.scalars(
            select(QAVersion)
            .join(QADraft, QADraft.id == QAVersion.draft_id)
            .where(
                QADraft.status == QADraftStatus.APPROVED,
                QAVersion.approved_at.is_not(None),
                QAVersion.version_number == QADraft.current_version_number,
            )
            .order_by(QAVersion.approved_at.desc())
        )
    )
    items = []
    for version in versions:
        if version.id in published_ids:
            continue
        draft = session.get(QADraft, version.draft_id)
        cluster = session.get(BadcaseCluster, draft.cluster_id) if draft else None
        alert = _cluster_alert(session, cluster.id) if cluster else None
        if draft is None or cluster is None or alert is None:
            continue
        items.append(
            {
                "qa_version_id": version.id,
                "version_number": version.version_number,
                "scenario": cluster.scenario or alert.scenario or "未分类场景",
                "question": str(version.content.get("question", "")),
                "answer": str(version.content.get("answer", "")),
                "approved_by": version.approved_by,
                "approved_at": version.approved_at.isoformat() if version.approved_at else None,
                "priority": alert.priority,
                "impact_count": alert.impact_count,
            }
        )
    return items


def _retest_item(session: Session, run: RetestRun) -> dict:
    alert = session.get(Alert, run.alert_id)
    version = session.get(QAVersion, run.qa_version_id) if run.qa_version_id else None
    rule = session.get(RuleVersion, run.rule_version_id)
    samples = list(
        session.scalars(select(RetestSample).where(RetestSample.retest_run_id == run.id))
    )
    method_run = retest_method_run(session, run, samples)
    replay_count = sum(sample.cohort == RetestCohort.REPLAY for sample in samples)
    new_count = sum(sample.cohort == RetestCohort.NEW for sample in samples)
    min_replay = int(rule.config.get("retest_min_replay", 1)) if rule else 1
    min_new = int(rule.config.get("retest_min_new", 1)) if rule else 1
    audit = session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.entity_type == "retest_run",
            AuditEvent.entity_id == run.id,
            AuditEvent.action == "qa_published",
        )
        .order_by(AuditEvent.created_at.desc())
    )
    state = _workspace_state(run, replay_count, new_count, min_replay, min_new)
    return {
        "id": run.id,
        "workspace_state": state,
        "status": run.status.value,
        "scenario": alert.scenario if alert else "未分类场景",
        "priority": alert.priority if alert else "P2",
        "impact_count": alert.impact_count if alert else 0,
        "qa_version_id": version.id if version else None,
        "qa_version_number": version.version_number if version else None,
        "question": str(version.content.get("question", "")) if version else "",
        "answer": str(version.content.get("answer", "")) if version else "",
        "published_by": audit.actor if audit else "",
        "published_at": (audit.created_at if audit else run.created_at).isoformat(),
        "release_note": str(audit.payload.get("release_note", "")) if audit else "",
        "replay_samples": {"available": replay_count, "required": min_replay},
        "new_samples": {"available": new_count, "required": min_new},
        "before_pass_rate": float(run.before_pass_rate) if run.before_pass_rate is not None else None,
        "replay_pass_rate": (
            float(run.replay_pass_rate) if run.replay_pass_rate is not None else None
        ),
        "new_sample_pass_rate": (
            float(run.new_sample_pass_rate) if run.new_sample_pass_rate is not None else None
        ),
        "locked_rule": {
            "rule_version": rule.version if rule else "",
            "prompt_version": method_run.prompt_version.version if method_run else "",
            "model": method_run.model if method_run else "",
            "threshold": float(method_run.template.threshold) if method_run else None,
            "pass_rate_threshold": (
                float(rule.config.get("retest_pass_threshold", 0.8)) if rule else None
            ),
        },
    }


def _workspace_state(
    run: RetestRun, replay_count: int, new_count: int, min_replay: int, min_new: int
) -> str:
    if run.status == RetestStatus.RECOVERED:
        return "recovered"
    if run.status == RetestStatus.NOT_RECOVERED:
        return "not_recovered"
    if run.status == RetestStatus.FAILED:
        return "failed"
    if run.status == RetestStatus.RUNNING:
        return "interrupted" if _is_stale_running(run) else "running"
    if replay_count >= min_replay and new_count >= min_new:
        return "ready"
    return "waiting_samples"


def _source_run(session: Session, retest: RetestRun) -> EvaluationRun | None:
    if retest.qa_version_id is None:
        return None
    version = session.get(QAVersion, retest.qa_version_id)
    draft = session.get(QADraft, version.draft_id) if version else None
    cluster = session.get(BadcaseCluster, draft.cluster_id) if draft else None
    return session.get(EvaluationRun, cluster.run_id) if cluster else None


def retest_method_run(
    session: Session,
    retest: RetestRun,
    samples: list[RetestSample] | None = None,
) -> EvaluationRun | None:
    selected = samples or list(
        session.scalars(select(RetestSample).where(RetestSample.retest_run_id == retest.id))
    )
    result_id = next(
        (
            sample.retest_evaluation_result_id
            for sample in selected
            if sample.retest_evaluation_result_id is not None
        ),
        None,
    )
    if result_id is not None:
        result = session.get(EvaluationResult, result_id)
        if result is not None:
            return session.get(EvaluationRun, result.run_id)
    planned = _planned_retest_evaluation_run(session, retest.id)
    if planned is not None:
        return planned
    return _source_run(session, retest)


def _planned_retest_evaluation_run(session: Session, retest_id: str) -> EvaluationRun | None:
    audit = session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.entity_type == "retest_run",
            AuditEvent.entity_id == retest_id,
            AuditEvent.action == "qa_published",
        )
        .order_by(AuditEvent.created_at.desc())
    )
    evaluation_run_id = audit.payload.get("evaluation_run_id") if audit else None
    return session.get(EvaluationRun, evaluation_run_id) if evaluation_run_id else None


def _copy_evaluation_run(
    session: Session, source: EvaluationRun, status: RunStatus
) -> EvaluationRun:
    run = EvaluationRun(
        template_id=source.template_id,
        prompt_version_id=source.prompt_version_id,
        rule_version_id=source.rule_version_id,
        quality_standard_version_id=source.quality_standard_version_id,
        provider=source.provider,
        model=source.model,
        model_parameters=dict(source.model_parameters),
        status=status,
    )
    session.add(run)
    session.flush()
    return run


def _confidence(value: float) -> Confidence:
    if value >= 0.8:
        return Confidence.HIGH
    if value >= 0.5:
        return Confidence.MEDIUM
    return Confidence.LOW


def _is_stale_running(run: RetestRun) -> bool:
    return run.started_at is None or run.started_at <= utc_now() - STALE_RETEST_AFTER
