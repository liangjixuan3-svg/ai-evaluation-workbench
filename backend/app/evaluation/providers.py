from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from app.evaluation.contracts import (
    AttributionRequest,
    EvaluationRequest,
    ProviderAttribution,
    ProviderEvaluation,
    ProviderQADraft,
    QADraftRequest,
    validate_evidence_in_transcript,
)
from app.shared.enums import RootCause


class _EvaluationTransport(Protocol):
    """Internal raw transport contract implemented by provider adapters."""

    def evaluate(self, request: EvaluationRequest) -> ProviderEvaluation: ...

    def attribute(self, request: AttributionRequest) -> ProviderAttribution: ...

    def draft_qa(self, request: QADraftRequest) -> ProviderQADraft: ...


class ProviderResponseFormatError(ValueError):
    """Raised when a provider response cannot be parsed as one JSON object."""


@dataclass(frozen=True, slots=True)
class ProviderIdentity:
    provider: str
    model: str

    def __post_init__(self) -> None:
        if not self.provider.strip() or self.provider != self.provider.strip():
            raise ValueError("provider identity must be non-empty and trimmed")
        if not self.model.strip() or self.model != self.model.strip():
            raise ValueError("model identity must be non-empty and trimmed")


def _parse_response_object(response: str | bytes | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(response, Mapping):
        return dict(response)
    if not isinstance(response, (str, bytes)):
        raise ProviderResponseFormatError("provider response must be a JSON object")
    try:
        parsed = json.loads(response)
    except (TypeError, json.JSONDecodeError) as error:
        raise ProviderResponseFormatError("provider response is not valid JSON") from error
    if not isinstance(parsed, dict):
        raise ProviderResponseFormatError("provider response JSON must be an object")
    return parsed


def parse_evaluation_response(
    response: str | bytes | Mapping[str, Any], request: EvaluationRequest
) -> ProviderEvaluation:
    result = ProviderEvaluation.model_validate(_parse_response_object(response))
    validate_evidence_in_transcript(result, request.conversation)
    return result


def parse_attribution_response(
    response: str | bytes | Mapping[str, Any], request: AttributionRequest
) -> ProviderAttribution:
    result = ProviderAttribution.model_validate(_parse_response_object(response))
    validate_evidence_in_transcript(result, request.conversation)
    return result


def parse_qa_draft_response(
    response: str | bytes | Mapping[str, Any], request: QADraftRequest
) -> ProviderQADraft:
    result = ProviderQADraft.model_validate(_parse_response_object(response))
    validate_evidence_in_transcript(result, request.conversation)
    return result


class EvaluationProvider:
    """Public provider boundary that validates every delegated result against its request."""

    def __init__(self, transport: _EvaluationTransport, *, provider: str, model: str) -> None:
        self._transport = transport
        self._identity = ProviderIdentity(provider=provider, model=model)

    @property
    def identity(self) -> ProviderIdentity:
        return self._identity

    def evaluate(self, request: EvaluationRequest) -> ProviderEvaluation:
        result = self._transport.evaluate(request)
        self._validate_result(result, ProviderEvaluation, request.conversation)
        return result

    def attribute(self, request: AttributionRequest) -> ProviderAttribution:
        result = self._transport.attribute(request)
        self._validate_result(result, ProviderAttribution, request.conversation)
        return result

    def draft_qa(self, request: QADraftRequest) -> ProviderQADraft:
        result = self._transport.draft_qa(request)
        self._validate_result(result, ProviderQADraft, request.conversation)
        return result

    @staticmethod
    def _validate_result(
        result: object,
        expected_type: type[ProviderEvaluation | ProviderAttribution | ProviderQADraft],
        conversation: Any,
    ) -> None:
        if not isinstance(result, expected_type):
            raise TypeError(
                f"provider returned {type(result).__name__}, expected {expected_type.__name__}"
            )
        validate_evidence_in_transcript(result, conversation)


class _FakeEvaluationTransport:
    """Internal deterministic transport used by the public fake provider."""

    def evaluate(self, request: EvaluationRequest) -> ProviderEvaluation:
        evidence = self._first_evidence(request.conversation.messages)
        return ProviderEvaluation(
            dimensions={
                dimension: 100.0
                for dimension in (
                    "correctness",
                    "completeness",
                    "relevance",
                    "service_experience",
                    "compliance",
                )
            },
            reason="Deterministic development evaluation.",
            evidence=[evidence],
            confidence=1.0,
        )

    def attribute(self, request: AttributionRequest) -> ProviderAttribution:
        evidence = self._first_evidence(request.conversation.messages)
        return ProviderAttribution(
            root_cause=RootCause.OTHER,
            reason="Deterministic development attribution.",
            evidence=[evidence],
            confidence=1.0,
        )

    def draft_qa(self, request: QADraftRequest) -> ProviderQADraft:
        evidence = self._first_evidence(request.conversation.messages)
        return ProviderQADraft(
            content={
                "question": "待人工确认的问题",
                "answer": "此草稿由确定性开发供应商生成，需人工审核。",
                "applicability": "仅适用于当前对话场景。",
                "handling_steps": ["由人工确认业务规则后处理。"],
                "estimated_time": "需人工确认。",
                "escalation": "无法确认时转人工。",
            },
            reason="Deterministic development QA draft.",
            evidence=[evidence],
            confidence=1.0,
        )

    @staticmethod
    def _first_evidence(messages: tuple[Any, ...]) -> str:
        return next(message.content.strip() for message in messages if message.content.strip())


class FakeEvaluationProvider(EvaluationProvider):
    """Deterministic development provider with the same validation boundary as real adapters."""

    def __init__(self) -> None:
        super().__init__(_FakeEvaluationTransport(), provider="fake", model="deterministic-v1")
