from __future__ import annotations

import signal
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import session_factory
from app.evaluation.openai_compatible import build_evaluation_provider, provider_is_configured
from app.evaluation.providers import EvaluationProvider
from app.evaluation.service import run_evaluation_batch
from app.jobs.models import Job
from app.jobs.worker import run_worker_once
from app.operations.service import postprocess_evaluation
from app.shared.enums import JobStatus


def process_next_job(session: Session, provider: EvaluationProvider) -> bool:
    def handler(job: Job) -> None:
        if job.kind != "evaluation_batch":
            raise ValueError(f"unsupported job kind: {job.kind}")
        run_id = str(job.payload["run_id"])
        run_evaluation_batch(session, run_id, provider)
        next_retry = session.scalar(
            select(func.min(Job.run_after)).where(
                Job.idempotency_key.like(f"evaluation-item:{run_id}:%"),
                Job.status == JobStatus.QUEUED,
            )
        )
        if next_retry is not None:
            parent = session.get(Job, job.id)
            if parent is None:
                raise LookupError("evaluation batch job no longer exists")
            parent.status = JobStatus.QUEUED
            parent.run_after = next_retry
            parent.claimed_by = None
            parent.claimed_at = None
            session.commit()
        else:
            postprocess_evaluation(session, run_id)

    summary = run_worker_once(
        session,
        "evaluation-worker",
        handler,
        limit=1,
        kinds=frozenset({"evaluation_batch"}),
    )
    return summary.claimed > 0


def main() -> None:
    if not provider_is_configured(settings):
        raise SystemExit("真实模型尚未配置，请设置 LLM_BASE_URL、LLM_API_KEY 和 LLM_MODEL")
    provider = build_evaluation_provider(settings)
    running = True

    def stop(signum: int, frame: object) -> None:
        del signum, frame
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while running:
        with session_factory() as session:
            processed = process_next_job(session, provider)
        if not processed:
            time.sleep(1)


if __name__ == "__main__":
    main()
