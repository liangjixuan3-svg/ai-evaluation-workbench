from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.evaluation.contracts import EvaluationRequest, ProviderEvaluation
from app.evaluation.providers import EvaluationProvider, ProviderIdentity
from app.imports.models import ImportSession
from app.ingestion.models import Conversation, DataSource
from app.jobs.models import Job
from app.main import create_app
from app.operations.router import get_operation_provider
from app.operations.worker import process_next_job
from app.shared.types import utc_now


class TransientEvaluationTransport:
    identity = ProviderIdentity(provider="test", model="transient-v1")

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, request: EvaluationRequest) -> ProviderEvaluation:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary provider outage")
        evidence = request.conversation.messages[0].content
        return ProviderEvaluation(
            dimensions={
                "correctness": 90,
                "completeness": 90,
                "relevance": 90,
                "service_experience": 90,
                "compliance": 90,
            },
            reason="The answer meets the configured quality bar.",
            evidence=[evidence],
            confidence=0.9,
        )


def test_create_operation_runs_and_returns_real_results() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    source = DataSource(name=f"source-{uuid4().hex}", kind="json_upload")
    session.add(source)
    session.flush()
    for index in range(2):
        session.add(
            Conversation(
                data_source_id=source.id,
                external_id=f"dialog-{index}",
                scenario="refund",
                status="normal",
                body={
                    "messages": [
                        {"role": "user", "content": "退款进度？"},
                        {"role": "assistant", "content": "请稍候。"},
                    ]
                },
                occurred_at=datetime(2026, 7, 30, tzinfo=UTC),
            )
        )
    imported = ImportSession(
        filename="dialogs.json",
        file_hash=uuid4().hex,
        status="confirmed",
        document=[],
        candidate_paths=["$"],
        mapping={},
        result_summary={},
        record_count=2,
        error_count=0,
        confirmed_source_id=source.id,
        expires_at=utc_now(),
        confirmed_at=utc_now(),
    )
    session.add(imported)
    session.commit()
    provider = EvaluationProvider(TransientEvaluationTransport())
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_operation_provider] = lambda: provider

    async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/operations/evaluations",
                json={
                    "import_id": imported.id,
                    "sample_size": 2,
                    "strategy": "random",
                    "threshold": 75,
                    "seed": 20260730,
                },
            )
            process_next_job(session, provider)
            for job in session.scalars(select(Job).where(Job.status == "queued")):
                job.run_after = utc_now()
            session.commit()
            process_next_job(session, provider)
            detail = await client.get(
                f"/api/operations/evaluations/{created.json()['run_id']}"
            )
            results = await client.get(
                f"/api/operations/evaluations/{created.json()['run_id']}/results"
            )
            return created, detail, results

    created, detail, results = asyncio.run(exercise())

    assert created.status_code == 201
    assert detail.json()["stage"] == "completed"
    assert detail.json()["completed_count"] == 2
    assert len(results.json()["items"]) == 2
    session.close()
    engine.dispose()
