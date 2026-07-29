from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from app.jobs.models import Job
from app.jobs.repository import claim_jobs
from app.shared.enums import JobStatus
from app.shared.types import utc_now


@dataclass(frozen=True)
class WorkerSummary:
    claimed: int = 0
    succeeded: int = 0
    failed: int = 0
    manual_review: int = 0


def run_worker_once(
    session: Session,
    worker_id: str,
    handler: Callable[[Job], None],
    limit: int = 1,
) -> WorkerSummary:
    jobs = claim_jobs(session, worker_id, limit)
    succeeded = 0
    failed = 0
    manual_review = 0

    for claimed_job in jobs:
        try:
            handler(claimed_job)
        except Exception as error:
            session.rollback()
            job = session.get(Job, claimed_job.id)
            if job is None:
                raise
            job.attempts += 1
            job.last_error = str(error)
            job.claimed_by = None
            job.claimed_at = None
            if job.attempts >= job.max_attempts:
                job.status = JobStatus.MANUAL_REVIEW
                manual_review += 1
            else:
                job.status = JobStatus.QUEUED
                job.run_after = utc_now() + timedelta(seconds=2**job.attempts)
                failed += 1
            session.commit()
        else:
            job = session.get(Job, claimed_job.id)
            if job is None:
                raise RuntimeError(f"claimed job {claimed_job.id} no longer exists")
            job.status = JobStatus.SUCCEEDED
            job.claimed_by = None
            job.claimed_at = None
            job.last_error = None
            session.commit()
            succeeded += 1

    return WorkerSummary(
        claimed=len(jobs),
        succeeded=succeeded,
        failed=failed,
        manual_review=manual_review,
    )
