from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.evaluation.providers import FakeEvaluationProvider
from app.imports.models import ImportSession
from app.ingestion.models import Conversation, DataSource
from app.main import create_app
from app.operations.router import get_operation_provider
from app.operations.worker import process_next_job
from app.shared.types import utc_now


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
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_operation_provider] = FakeEvaluationProvider

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
            process_next_job(session, FakeEvaluationProvider())
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
