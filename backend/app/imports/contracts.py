from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.ingestion.contracts import ConversationInput


class ImportMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_path: str
    occurred_at_path: str
    message_mode: Literal["messages", "qa_pair"]
    id_path: str | None = None
    scenario_path: str | None = None
    status_path: str | None = None
    messages_path: str | None = None
    role_path: str | None = None
    content_path: str | None = None
    question_path: str | None = None
    answer_path: str | None = None
    timezone_name: str = "Asia/Shanghai"
    error_policy: Literal["block", "skip"] = "block"

    @model_validator(mode="after")
    def validate_message_paths(self) -> ImportMapping:
        if self.message_mode == "messages" and not all(
            (self.messages_path, self.role_path, self.content_path)
        ):
            raise ValueError("消息数组模式需要消息、角色和内容字段")
        if self.message_mode == "qa_pair" and not all((self.question_path, self.answer_path)):
            raise ValueError("问答模式需要问题和回答字段")
        return self


@dataclass(frozen=True, slots=True)
class ArrayCandidate:
    path: str
    length: int
    object_ratio: float
    sample: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class NormalizationError:
    row_index: int
    message: str


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    items: tuple[ConversationInput, ...]
    errors: tuple[NormalizationError, ...]
