from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.ingestion.contracts import ConversationInput
from app.ingestion.models import Conversation, DataSource
from app.ingestion.redaction import redact_conversation
from app.ingestion.service import ingest_conversations
from app.main import create_app


@pytest.fixture(scope="module")
def engine():
    value = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    try:
        yield value
    finally:
        value.dispose()


@pytest.fixture
def session(engine) -> Iterator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    value = Session(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield value
    finally:
        value.close()
        transaction.rollback()
        connection.close()


def fixture_items() -> list[ConversationInput]:
    fixture_path = Path(__file__).parents[1] / "fixtures" / "conversations.json"
    rows = json.loads(fixture_path.read_text(encoding="utf-8"))
    return [ConversationInput.from_mapping(row) for row in rows]


def test_ingestion_is_idempotent_and_preserves_the_original_source_body(session: Session) -> None:
    source = DataSource(name=f"simulated-{uuid4().hex}", kind="simulated")
    session.add(source)
    session.commit()
    items = fixture_items()

    first = ingest_conversations(session, source.id, items)
    second = ingest_conversations(session, source.id, items)
    stored = list(
        session.scalars(select(Conversation).where(Conversation.data_source_id == source.id))
    )
    first_conversation = session.scalar(
        select(Conversation).where(
            Conversation.data_source_id == source.id,
            Conversation.external_id == "refund-001",
        )
    )

    assert first.inserted == 5
    assert first.skipped == 1
    assert second.inserted == 0
    assert second.skipped == 6
    assert len(stored) == 5
    assert first_conversation is not None
    assert first_conversation.body == items[0].body
    assert redact_conversation(first_conversation).messages[0].content == (
        "我的订单 [ORDER_ID] 退款到哪了？电话 [PHONE]"
    )


def test_simulated_ingestion_route_uses_the_overridden_session(session: Session) -> None:
    source = DataSource(name=f"api-simulated-{uuid4().hex}", kind="simulated")
    session.add(source)
    session.commit()
    item = fixture_items()[0]
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session

    async def post_ingestion() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/api/ingestion/simulated",
                json={"source_id": source.id, "items": [item.as_dict()]},
            )

    try:
        response = asyncio.run(post_ingestion())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"inserted": 1, "skipped": 0}


def test_ingestion_rolls_back_failed_write_before_reusing_the_session(session: Session) -> None:
    failed_item = fixture_items()[0]

    with pytest.raises(IntegrityError):
        ingest_conversations(session, str(uuid4()), [failed_item])

    source = DataSource(name=f"recovered-{uuid4().hex}", kind="simulated")
    session.add(source)
    session.commit()
    summary = ingest_conversations(session, source.id, [fixture_items()[1]])

    assert summary.inserted == 1
    assert (
        session.scalar(
            select(Conversation).where(
                Conversation.data_source_id == source.id,
                Conversation.external_id == "logistics-001",
            )
        )
        is not None
    )
