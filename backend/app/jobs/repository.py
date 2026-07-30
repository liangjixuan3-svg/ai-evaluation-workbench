from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.jobs.models import Job
from app.shared.enums import JobStatus
from app.shared.types import utc_now

DEFAULT_MAX_ATTEMPTS = 3


def enqueue_job(
    session: Session,
    kind: str,
    payload: dict[str, Any],
    idempotency_key: str,
) -> Job:
    existing = session.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
    if existing is not None:
        session.commit()
        return existing

    max_attempts = payload.get("max_attempts", DEFAULT_MAX_ATTEMPTS)
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer")

    job = Job(
        kind=kind,
        payload=payload,
        idempotency_key=idempotency_key,
        max_attempts=max_attempts,
    )
    try:
        with session.begin_nested():
            session.add(job)
            session.flush()
    except IntegrityError:
        # A concurrent enqueuer may have won the unique-key race.
        existing = session.scalar(
            select(Job).where(Job.idempotency_key == idempotency_key).with_for_update()
        )
        if existing is None:
            session.rollback()
            raise
        session.commit()
        return existing
    session.commit()
    return job


def claim_jobs(
    session: Session,
    worker_id: str,
    limit: int,
    kinds: frozenset[str] | None = None,
) -> list[Job]:
    if limit < 1:
        return []

    query = select(Job).where(Job.status == JobStatus.QUEUED, Job.run_after <= utc_now())
    if kinds:
        query = query.where(Job.kind.in_(kinds))
    jobs = list(
        session.scalars(
            query
            .order_by(Job.created_at, Job.id)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
    )
    claimed_at = utc_now()
    for job in jobs:
        job.status = JobStatus.CLAIMED
        job.claimed_by = worker_id
        job.claimed_at = claimed_at
    session.commit()
    return jobs


def claim_job(session: Session, job_id: str, worker_id: str) -> Job | None:
    claimed_at = utc_now()
    result = session.execute(
        update(Job)
        .where(
            Job.id == job_id,
            Job.status == JobStatus.QUEUED,
            Job.run_after <= claimed_at,
        )
        .values(
            status=JobStatus.CLAIMED,
            claimed_by=worker_id,
            claimed_at=claimed_at,
        )
    )
    claimed = result.rowcount == 1
    session.commit()
    if not claimed:
        return None
    return session.get(Job, job_id)
