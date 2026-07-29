from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True)
class ConversationInput:
    external_id: str
    scenario: str | None
    status: str | None
    occurred_at: datetime
    body: dict[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ConversationInput:
        occurred_at = value["occurred_at"]
        if isinstance(occurred_at, str):
            occurred_at = datetime.fromisoformat(occurred_at)
        if not isinstance(occurred_at, datetime):
            raise TypeError("occurred_at must be an ISO-8601 datetime")
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")

        body = value["body"]
        if not isinstance(body, dict):
            raise TypeError("body must be an object")

        return cls(
            external_id=str(value["external_id"]),
            scenario=value.get("scenario"),
            status=value.get("status"),
            occurred_at=occurred_at,
            body=body,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "external_id": self.external_id,
            "scenario": self.scenario,
            "status": self.status,
            "occurred_at": self.occurred_at.isoformat(),
            "body": self.body,
        }


@dataclass(frozen=True)
class NormalizedConversation:
    external_id: str
    scenario: str | None
    status: str | None
    occurred_at: datetime
    messages: tuple[Message, ...]


@dataclass(frozen=True)
class SampleCandidate:
    id: UUID
    scenario: str | None
    is_risk: bool
