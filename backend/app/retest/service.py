from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import Alert, AlertResult, Task
from app.analysis.models import BadcaseCluster, ClusterMember
from app.evaluation.models import EvaluationResult, EvaluationRun, RuleVersion
from app.ingestion.models import Conversation
from app.remediation.models import QADraft, QAVersion
from app.retest.models import RetestRun, RetestSample
from app.shared.audit import record_audit
from app.shared.enums import AlertStatus, RetestCohort, RetestStatus, TaskStatus, TaskType
from app.shared.types import new_uuid, utc_now


class InvalidRetestState(ValueError):
    pass


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


def mark_published(session: Session, qa_version_id: str, actor: str) -> RetestRun:
    if not actor.strip():
        raise InvalidRetestState("actor is required")
    version = session.get(QAVersion, qa_version_id)
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
            RetestRun.status.in_((RetestStatus.QUEUED, RetestStatus.RUNNING)),
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
        payload={"qa_version_id": version.id, "alert_id": alert.id},
    )
    session.commit()
    return retest


def build_retest_sample(session: Session, run_id: str) -> list[RetestSample]:
    retest = session.get(RetestRun, run_id)
    if retest is None:
        raise LookupError("retest run does not exist")
    existing = list(
        session.scalars(select(RetestSample).where(RetestSample.retest_run_id == run_id))
    )
    if existing:
        return existing
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
    samples = [
        RetestSample(
            retest_run_id=retest.id,
            conversation_id=result.conversation_id,
            cohort=RetestCohort.REPLAY,
            source_evaluation_result_id=result.id,
        )
        for result in source_results
    ]
    replay_conversation_ids = {sample.conversation_id for sample in samples}
    new_conversations = list(
        session.scalars(
            select(Conversation)
            .where(
                Conversation.scenario == alert.scenario,
                Conversation.created_at >= retest.created_at,
                Conversation.id.not_in(replay_conversation_ids),
            )
            .order_by(Conversation.created_at.desc())
            .limit(new_limit)
        )
    )
    samples.extend(
        RetestSample(
            retest_run_id=retest.id,
            conversation_id=conversation.id,
            cohort=RetestCohort.NEW,
        )
        for conversation in new_conversations
    )
    session.add_all(samples)
    retest.status = RetestStatus.RUNNING
    retest.started_at = utc_now()
    session.commit()
    return samples


def complete_retest(session: Session, run_id: str, actor: str) -> RetestRun:
    retest = session.scalar(select(RetestRun).where(RetestRun.id == run_id).with_for_update())
    if retest is None:
        raise LookupError("retest run does not exist")
    if retest.status not in (RetestStatus.QUEUED, RetestStatus.RUNNING):
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
