from datetime import UTC, datetime

from app.ingestion.contracts import ConversationInput, Message
from app.ingestion.redaction import redact_conversation, redact_text


def test_redaction_removes_phone_and_order_id() -> None:
    text = "电话 13800138000，订单 ORD-20260729-8899"

    assert redact_text(text) == "电话 [PHONE]，订单 [ORDER_ID]"


def test_redaction_keeps_phone_like_sku_and_redacts_chinese_adjacent_order_id() -> None:
    text = "SKUAB13800138000CD，订单ORD-20260729-8899"

    assert redact_text(text) == "SKUAB13800138000CD，订单[ORDER_ID]"


def test_redaction_returns_a_copy_without_mutating_source_body() -> None:
    source = ConversationInput(
        external_id="source-1",
        scenario="any-scenario",
        status="open",
        occurred_at=datetime(2026, 7, 29, tzinfo=UTC),
        body={"messages": [{"role": "user", "content": "请联系 13800138000"}]},
    )

    result = redact_conversation(source)

    assert result.messages == (Message(role="user", content="请联系 [PHONE]"),)
    assert source.body == {"messages": [{"role": "user", "content": "请联系 13800138000"}]}
