from __future__ import annotations

import re
from typing import Any, Protocol

from app.ingestion.contracts import ConversationInput, Message, NormalizedConversation

PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
ORDER_ID_PATTERN = re.compile(r"\bORD-\d{8}-[A-Za-z0-9]+\b")
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


class ConversationLike(Protocol):
    external_id: str
    scenario: str | None
    status: str | None
    occurred_at: Any
    body: dict[str, Any]


def redact_text(text: str) -> str:
    redacted = PHONE_PATTERN.sub("[PHONE]", text)
    redacted = ORDER_ID_PATTERN.sub("[ORDER_ID]", redacted)
    return EMAIL_PATTERN.sub("[EMAIL]", redacted)


def redact_conversation(
    conversation: ConversationInput | ConversationLike,
) -> NormalizedConversation:
    raw_messages = conversation.body.get("messages")
    if not isinstance(raw_messages, list):
        raise TypeError("conversation body must contain a messages list")

    messages: list[Message] = []
    for raw_message in raw_messages:
        if not isinstance(raw_message, dict):
            raise TypeError("each message must be an object")
        role = raw_message.get("role")
        content = raw_message.get("content")
        if not isinstance(role, str) or not isinstance(content, str):
            raise TypeError("each message requires string role and content")
        messages.append(Message(role=role, content=redact_text(content)))

    return NormalizedConversation(
        external_id=conversation.external_id,
        scenario=conversation.scenario,
        status=conversation.status,
        occurred_at=conversation.occurred_at,
        messages=tuple(messages),
    )
