from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ingestion.contracts import NormalizedConversation
from app.ingestion.redaction import redact_text
from app.shared.enums import RootCause

EVALUATION_DIMENSIONS = frozenset(
    {
        "correctness",
        "completeness",
        "relevance",
        "service_experience",
        "compliance",
    }
)


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _ConversationRequest(_StrictContract):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", strict=True)

    conversation: NormalizedConversation

    @field_validator("conversation")
    @classmethod
    def require_transcript_content(cls, value: NormalizedConversation) -> NormalizedConversation:
        if not any(message.content.strip() for message in value.messages):
            raise ValueError("conversation must include transcript content")
        if any(redact_text(message.content) != message.content for message in value.messages):
            raise ValueError("conversation transcript must be redacted before provider evaluation")
        return value


class EvaluationRequest(_ConversationRequest):
    criteria: dict = Field(default_factory=dict)


class _ProviderResponse(_StrictContract):
    reason: str
    evidence: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason must not be empty")
        return value

    @field_validator("evidence")
    @classmethod
    def require_nonempty_evidence(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("evidence entries must not be empty")
        return cleaned


class ProviderEvaluation(_ProviderResponse):
    dimensions: dict[str, float]
    severe_factual_error: bool = False
    severe_compliance_error: bool = False

    @field_validator("dimensions")
    @classmethod
    def validate_dimensions(cls, value: dict[str, float]) -> dict[str, float]:
        actual_dimensions = frozenset(value)
        unknown_dimensions = actual_dimensions - EVALUATION_DIMENSIONS
        missing_dimensions = EVALUATION_DIMENSIONS - actual_dimensions
        if unknown_dimensions:
            raise ValueError(f"unknown dimensions: {sorted(unknown_dimensions)}")
        if missing_dimensions:
            raise ValueError(f"missing dimensions: {sorted(missing_dimensions)}")
        if any(not math.isfinite(score) or score < 0 or score > 100 for score in value.values()):
            raise ValueError("dimension scores must be between 0 and 100")
        return value


class AttributionRequest(_ConversationRequest):
    evaluation: ProviderEvaluation


class ProviderAttribution(_ProviderResponse):
    root_cause: RootCause = Field(strict=False)


class QADraftRequest(_ConversationRequest):
    attribution: ProviderAttribution


class QADraftContent(_StrictContract):
    question: str
    answer: str
    applicability: str
    handling_steps: list[str] = Field(min_length=1)
    estimated_time: str
    escalation: str

    @field_validator("question", "answer", "applicability", "estimated_time", "escalation")
    @classmethod
    def require_nonempty_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("QA draft text fields must not be empty")
        return value

    @field_validator("handling_steps")
    @classmethod
    def require_nonempty_steps(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("QA draft handling steps must not be empty")
        return cleaned


class ProviderQADraft(_ProviderResponse):
    content: QADraftContent


class EvaluationOutcome(_StrictContract):
    score: float = Field(ge=0, le=100)
    passed: bool


def validate_evidence_in_transcript(
    response: _ProviderResponse, conversation: NormalizedConversation
) -> None:
    transcript = "\n".join(message.content for message in conversation.messages)
    absent_evidence = [item for item in response.evidence if item not in transcript]
    if absent_evidence:
        raise ValueError("evidence must be quoted from the input transcript")
