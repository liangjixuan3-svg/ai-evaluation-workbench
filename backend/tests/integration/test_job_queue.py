from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.jobs.models import Job
from app.jobs.repository import claim_jobs, enqueue_job
from app.jobs.worker import run_worker_once
from app.shared.enums import JobStatus
from app.shared.types import utc_now


@pytest.fixture(scope="module")
def engine():
    value = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    try:
        yield value
    finally:
        value.dispose()


def test_enqueue_idempotency_key_returns_the_existing_logical_job(engine) -> None:
    key = f"evaluation-{uuid4().hex}"
    with Session(engine, expire_on_commit=False) as session:
        try:
            first = enqueue_job(session, "evaluation_batch", {"run_id": "run-1"}, key)
            second = enqueue_job(session, "evaluation_batch", {"run_id": "run-1"}, key)

            jobs = list(session.scalars(select(Job).where(Job.idempotency_key == key)))

            assert first.id == second.id
            assert len(jobs) == 1
            assert jobs[0].status == JobStatus.QUEUED
        finally:
            session.execute(delete(Job).where(Job.idempotency_key == key))
            session.commit()


def test_concurrent_claimers_never_return_the_same_job(engine) -> None:
    key_prefix = f"claim-{uuid4().hex}"
    with Session(engine, expire_on_commit=False) as setup_session:
        jobs = [
            enqueue_job(
                setup_session,
                "evaluation_item",
                {"conversation_id": str(index)},
                f"{key_prefix}-{index}",
            )
            for index in range(4)
        ]

    barrier = Barrier(2)

    def claim(worker_id: str) -> set[str]:
        with Session(engine, expire_on_commit=False) as worker_session:
            barrier.wait()
            return {job.id for job in claim_jobs(worker_session, worker_id, limit=2)}

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first, second = list(executor.map(claim, ("worker-a", "worker-b")))

        assert first
        assert second
        assert first.isdisjoint(second)
        assert first | second == {job.id for job in jobs}
    finally:
        with Session(engine) as cleanup_session:
            cleanup_session.execute(delete(Job).where(Job.idempotency_key.like(f"{key_prefix}%")))
            cleanup_session.commit()


def test_worker_requeues_failure_with_backoff_then_marks_manual_review(engine) -> None:
    key = f"retry-{uuid4().hex}"
    with Session(engine, expire_on_commit=False) as session:
        job = enqueue_job(session, "evaluation_item", {"max_attempts": 2}, key)
        try:
            first = run_worker_once(
                session,
                worker_id="worker-a",
                handler=lambda claimed: (_ for _ in ()).throw(RuntimeError("provider timeout")),
            )
            failed_once = session.get(Job, job.id)

            assert first.failed == 1
            assert failed_once is not None
            assert failed_once.status == JobStatus.QUEUED
            assert failed_once.attempts == 1
            assert failed_once.run_after >= utc_now() + timedelta(seconds=1)
            assert failed_once.last_error == "provider timeout"

            failed_once.run_after = utc_now()
            session.commit()
            second = run_worker_once(
                session,
                worker_id="worker-a",
                handler=lambda claimed: (_ for _ in ()).throw(RuntimeError("provider timeout")),
            )
            exhausted = session.get(Job, job.id)

            assert second.manual_review == 1
            assert exhausted is not None
            assert exhausted.status == JobStatus.MANUAL_REVIEW
            assert exhausted.attempts == 2
        finally:
            session.execute(delete(Job).where(Job.idempotency_key == key))
            session.commit()
