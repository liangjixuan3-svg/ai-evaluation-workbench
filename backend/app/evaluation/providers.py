from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

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


@runtime_checkable
class EvaluationProvider(Protocol):
    """Unvalidated provider implementation contract for transport adapters."""

    def evaluate(self, request: EvaluationRequest) -> ProviderEvaluation: ...

    def attribute(self, request: AttributionRequest) -> ProviderAttribution: ...

    def draft_qa(self, request: QADraftRequest) -> ProviderQADraft: ...


class ProviderResponseFormatError(ValueError):
    """Raised when a provider response cannot be parsed as one JSON object."""


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


class ValidatedEvaluationProvider:
    """Public provider boundary that validates every delegated result against its request."""

    def __init__(self, provider: EvaluationProvider) -> None:
        self._provider = provider

    def evaluate(self, request: EvaluationRequest) -> ProviderEvaluation:
        result = self._provider.evaluate(request)
        self._validate_result(result, ProviderEvaluation, request.conversation)
        return result

    def attribute(self, request: AttributionRequest) -> ProviderAttribution:
        result = self._provider.attribute(request)
        self._validate_result(result, ProviderAttribution, request.conversation)
        return result

    def draft_qa(self, request: QADraftRequest) -> ProviderQADraft:
        result = self._provider.draft_qa(request)
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


class FakeEvaluationProvider:
    """Deterministic development provider that never receives unredacted source data."""

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
