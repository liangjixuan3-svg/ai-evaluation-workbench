from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.db import get_session
from app.imports.models import ImportSession
from app.ingestion.models import Conversation, DataSource
from app.main import create_app
from app.shared.audit import AuditEvent


def test_upload_preview_confirm_is_idempotent() -> None:
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    session = Session(engine, expire_on_commit=False)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    suffix = uuid4().hex
    document = {
        "data": [
            {
                "id": f"dialog-{suffix}",
                "time": datetime(2026, 7, 30, 9, tzinfo=UTC).isoformat(),
                "question": "手机号 13800138000",
                "answer": "请稍候。",
                "metadata": {"channel": "app"},
            }
        ]
    }

    async def exercise() -> tuple[dict, dict, dict, dict]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            uploaded = await client.post(
                "/api/imports/json",
                json={"filename": "dialogs.json", "document": document},
            )
            preview = await client.post(
                f"/api/imports/{uploaded.json()['id']}/preview",
                json={
                    "mapping": {
                        "record_path": "data",
                        "id_path": "id",
                        "occurred_at_path": "time",
                        "message_mode": "qa_pair",
                        "question_path": "question",
                        "answer_path": "answer",
                    },
                    "timezone_name": "Asia/Shanghai",
                    "error_policy": "block",
                },
            )
            assert (
                session.query(DataSource).filter(DataSource.name == f"source-{suffix}").count() == 0
            )
            first = await client.post(
                f"/api/imports/{uploaded.json()['id']}/confirm",
                json={"source_name": f"source-{suffix}", "actor": "operator-1"},
            )
            second = await client.post(
                f"/api/imports/{uploaded.json()['id']}/confirm",
                json={"source_name": f"source-{suffix}", "actor": "operator-1"},
            )
            return uploaded.json(), preview.json(), first.json(), second.json()

    uploaded, preview, first, second = asyncio.run(exercise())
    try:
        assert preview["valid_count"] == 1
        assert preview["items"][0]["redacted_messages"][0]["content"] == "手机号 [PHONE]"
        assert first == second
        assert first["inserted"] == 1
        assert session.query(Conversation).filter_by(data_source_id=first["source_id"]).count() == 1
    finally:
        session.rollback()
        session.execute(delete(AuditEvent).where(AuditEvent.entity_id.in_((uploaded["id"],))))
        if first.get("source_id"):
            session.execute(
                delete(Conversation).where(Conversation.data_source_id == first["source_id"])
            )
        session.execute(delete(ImportSession).where(ImportSession.id == uploaded["id"]))
        if first.get("source_id"):
            session.execute(delete(DataSource).where(DataSource.id == first["source_id"]))
        session.commit()
        session.close()
        engine.dispose()
