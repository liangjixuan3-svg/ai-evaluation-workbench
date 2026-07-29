from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from time import perf_counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.evaluation.contracts import EvaluationRequest, ProviderEvaluation
from app.evaluation.models import EvaluationResult, EvaluationRun, ModelCallRecord
from app.evaluation.providers import EvaluationProvider, ProviderIdentity
from app.evaluation.scoring import calculate_outcome
from app.ingestion.models import Conversation, SamplingBatchConversation
from app.ingestion.redaction import redact_conversation
from app.jobs.models import Job
from app.jobs.repository import claim_job, enqueue_job
from app.shared.audit import record_audit
from app.shared.enums import Confidence, JobStatus, RunStatus
from app.shared.types import utc_now


@dataclass(frozen=True)
class RunSummary:
    succeeded: int
    failed: int


@dataclass(frozen=True)
class _TemplateSnapshot:
    weights: dict[str, object]
    threshold: object


def run_evaluation_batch(
    session: Session,
    run_id: str,
    provider: EvaluationProvider,
) -> RunSummary:
    if not isinstance(provider, EvaluationProvider):
        raise TypeError("provider must be a validated EvaluationProvider")

    run = session.get(EvaluationRun, run_id)
    if run is None:
        raise LookupError(f"evaluation run {run_id} does not exist")
    identity = provider.identity
    if run.provider != identity.provider or run.model != identity.model:
        session.rollback()
        raise ValueError("provider identity does not match evaluation run provider/model")
    if run.sampling_batch_id is None:
        raise ValueError("evaluation run requires a sampling batch")

    if run.started_at is None:
        run.started_at = utc_now()
    run.status = RunStatus.RUNNING
    session.commit()

    conversation_ids = list(
        session.scalars(
            select(SamplingBatchConversation.conversation_id)
            .where(SamplingBatchConversation.batch_id == run.sampling_batch_id)
            .order_by(SamplingBatchConversation.conversation_id)
        )
    )
    session.commit()

    item_jobs: list[Job] = []
    for conversation_id in conversation_ids:
        item_job = enqueue_job(
            session,
            "evaluation_item",
            {"run_id": run_id, "conversation_id": conversation_id},
            _item_key(run_id, conversation_id),
        )
        item_jobs.append(item_job)

        if _result_exists(session, run_id, conversation_id):
            _mark_job_succeeded(session, item_job.id)
            continue
        session.commit()

        item_job = claim_job(session, item_job.id, f"evaluation-run:{run_id}")
        if item_job is None:
            continue

        _evaluate_item(session, run_id, conversation_id, item_job.id, provider, identity)

    return _finish_run(session, run_id, conversation_ids, item_jobs)


def _evaluate_item(
    session: Session,
    run_id: str,
    conversation_id: str,
    job_id: str,
    provider: EvaluationProvider,
    identity: ProviderIdentity,
) -> None:
    started = perf_counter()
    try:
        run = session.get(EvaluationRun, run_id)
        conversation = session.get(Conversation, conversation_id)
        if run is None or conversation is None:
            raise LookupError("evaluation run or conversation no longer exists")

        request = EvaluationRequest(conversation=redact_conversation(conversation))
        template = _TemplateSnapshot(
            weights=dict(run.template.weights), threshold=run.template.threshold
        )
        session.commit()

        provider_result = provider.evaluate(request)
        duration_ms = round((perf_counter() - started) * 1000)
        outcome = calculate_outcome(provider_result, template)
        _checkpoint_success(
            session,
            run_id,
            conversation_id,
            job_id,
            provider_result,
            outcome.score,
            outcome.passed,
            duration_ms,
            identity,
        )
    except Exception as error:  # noqa: BLE001 - provider failures are isolated per item.
        duration_ms = round((perf_counter() - started) * 1000)
        session.rollback()
        _checkpoint_failure(session, run_id, job_id, error, duration_ms, identity)


def _checkpoint_success(
    session: Session,
    run_id: str,
    conversation_id: str,
    job_id: str,
    provider_result: ProviderEvaluation,
    score: float,
    passed: bool,
    duration_ms: int,
    identity: ProviderIdentity,
) -> None:
    run = session.get(EvaluationRun, run_id)
    job = session.get(Job, job_id)
    if run is None or job is None:
        raise LookupError("evaluation checkpoint parent no longer exists")

    session.add(
        EvaluationResult(
            run_id=run_id,
            conversation_id=conversation_id,
            total_score=Decimal(str(score)),
            dimension_scores=provider_result.dimensions,
            passed=passed,
            reason=provider_result.reason,
            evidence=provider_result.evidence,
            confidence=_confidence(provider_result.confidence),
            severe_factual_error=provider_result.severe_factual_error,
            severe_compliance_error=provider_result.severe_compliance_error,
        )
    )
    session.add(_call_record(run, identity, "succeeded", duration_ms))
    job.status = JobStatus.SUCCEEDED
    job.claimed_by = None
    job.claimed_at = None
    job.last_error = None
    record_audit(
        session,
        actor="evaluation-worker",
        action="evaluation_item_succeeded",
        entity_type="conversation",
        entity_id=conversation_id,
        payload=_lineage_payload(run, identity),
    )
    session.commit()


def _checkpoint_failure(
    session: Session,
    run_id: str,
    job_id: str,
    error: Exception,
    duration_ms: int,
    identity: ProviderIdentity,
) -> None:
    run = session.get(EvaluationRun, run_id)
    job = session.get(Job, job_id)
    if run is None or job is None:
        raise LookupError("evaluation failure checkpoint parent no longer exists")

    _stage_failure(session, run, job, error, duration_ms, identity)
    try:
        record_audit(
            session,
            actor="evaluation-worker",
            action=(
                "evaluation_item_manual_review"
                if job.status == JobStatus.MANUAL_REVIEW
                else "evaluation_item_retry_scheduled"
            ),
            entity_type="job",
            entity_id=job.id,
            payload={
                **_lineage_payload(run, identity),
                "attempts": job.attempts,
                "error": str(error),
            },
        )
    except Exception:  # noqa: BLE001 - retry state must survive an audit outage.
        session.rollback()
        run = session.get(EvaluationRun, run_id)
        job = session.get(Job, job_id)
        if run is None or job is None:
            raise LookupError("evaluation failure checkpoint parent no longer exists")
        _stage_failure(session, run, job, error, duration_ms, identity)
    session.commit()


def _stage_failure(
    session: Session,
    run: EvaluationRun,
    job: Job,
    error: Exception,
    duration_ms: int,
    identity: ProviderIdentity,
) -> None:
    job.attempts += 1
    job.last_error = str(error)
    job.claimed_by = None
    job.claimed_at = None
    if job.attempts >= job.max_attempts:
        job.status = JobStatus.MANUAL_REVIEW
    else:
        job.status = JobStatus.QUEUED
        job.run_after = utc_now() + timedelta(seconds=2**job.attempts)
    session.add(
        _call_record(
            run,
            identity,
            "failed",
            duration_ms,
            error_code=type(error).__name__[:64],
        )
    )


def _finish_run(
    session: Session,
    run_id: str,
    conversation_ids: list[str],
    item_jobs: list[Job],
) -> RunSummary:
    succeeded = session.scalar(
        select(func.count(EvaluationResult.id)).where(EvaluationResult.run_id == run_id)
    )
    succeeded_count = int(succeeded or 0)
    failed_count = len(conversation_ids) - succeeded_count
    refreshed_jobs = [session.get(Job, job.id) for job in item_jobs]
    has_pending_retry = any(
        job is not None and job.status in {JobStatus.QUEUED, JobStatus.CLAIMED}
        for job in refreshed_jobs
    )

    run = session.get(EvaluationRun, run_id)
    if run is None:
        raise LookupError(f"evaluation run {run_id} no longer exists")
    run.succeeded_count = succeeded_count
    run.failed_count = failed_count
    if failed_count == 0:
        run.status = RunStatus.SUCCEEDED
        run.completed_at = utc_now()
    elif succeeded_count > 0:
        run.status = RunStatus.PARTIAL
        run.completed_at = None if has_pending_retry else utc_now()
    elif has_pending_retry:
        run.status = RunStatus.FAILED
        run.completed_at = None
    else:
        run.status = RunStatus.MANUAL_REVIEW
        run.completed_at = utc_now()
    session.commit()
    return RunSummary(succeeded=succeeded_count, failed=failed_count)


def _result_exists(session: Session, run_id: str, conversation_id: str) -> bool:
    return (
        session.scalar(
            select(EvaluationResult.id).where(
                EvaluationResult.run_id == run_id,
                EvaluationResult.conversation_id == conversation_id,
            )
        )
        is not None
    )


def _mark_job_succeeded(session: Session, job_id: str) -> None:
    job = session.get(Job, job_id)
    if job is not None and job.status != JobStatus.SUCCEEDED:
        job.status = JobStatus.SUCCEEDED
        job.claimed_by = None
        job.claimed_at = None
        job.last_error = None
    session.commit()


def _call_record(
    run: EvaluationRun,
    identity: ProviderIdentity,
    status: str,
    duration_ms: int,
    error_code: str | None = None,
) -> ModelCallRecord:
    return ModelCallRecord(
        evaluation_run_id=run.id,
        provider=identity.provider,
        model=identity.model,
        operation="evaluation",
        input_tokens=0,
        output_tokens=0,
        estimated_cost=Decimal(0),
        status=status,
        error_code=error_code,
        duration_ms=duration_ms,
    )


def _lineage_payload(run: EvaluationRun, identity: ProviderIdentity) -> dict[str, str]:
    return {
        "provider": identity.provider,
        "model": identity.model,
        "template_version": run.template.version,
        "prompt_version": run.prompt_version.version,
        "rule_version": run.rule_version.version,
    }


def _confidence(value: float) -> Confidence:
    if value >= 0.8:
        return Confidence.HIGH
    if value >= 0.5:
        return Confidence.MEDIUM
    return Confidence.LOW


def _item_key(run_id: str, conversation_id: str) -> str:
    return f"evaluation-item:{run_id}:{conversation_id}"
