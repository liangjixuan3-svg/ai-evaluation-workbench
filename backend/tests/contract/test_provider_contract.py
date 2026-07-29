from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.contracts import (
    AttributionRequest,
    EvaluationRequest,
    ProviderEvaluation,
    QADraftRequest,
)
from app.evaluation.providers import (
    EvaluationProvider,
    FakeEvaluationProvider,
    ProviderResponseFormatError,
    parse_attribution_response,
    parse_evaluation_response,
)
from app.ingestion.contracts import Message, NormalizedConversation

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "provider_responses.json"


@pytest.fixture
def provider_responses() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text())


@pytest.fixture
def evaluation_request() -> EvaluationRequest:
    conversation = NormalizedConversation(
        external_id="conversation-1",
        scenario="refund_progress",
        status="closed",
        occurred_at=datetime(2026, 7, 30, tzinfo=UTC),
        messages=(
            Message(role="user", content="退款什么时候到账？"),
            Message(role="assistant", content="退款将在三个工作日内原路退回。"),
        ),
    )
    return EvaluationRequest(conversation=conversation)


def test_valid_fixture_parses_and_keeps_traceable_evidence(
    provider_responses: dict[str, object], evaluation_request: EvaluationRequest
) -> None:
    result = parse_evaluation_response(
        json.dumps(provider_responses["valid_evaluation"]), evaluation_request
    )

    assert result.dimensions["correctness"] == 90
    assert result.evidence == ["退款将在三个工作日内原路退回"]


@pytest.mark.parametrize(
    ("change", "description"),
    [
        (lambda value: value["dimensions"].update({"invented": 50}), "unknown dimension"),
        (lambda value: value["dimensions"].update({"correctness": 101}), "out-of-range score"),
        (lambda value: value["dimensions"].update({"correctness": float("nan")}), "NaN score"),
        (lambda value: value.update({"reason": "   "}), "empty reason"),
        (lambda value: value.update({"confidence": 1.01}), "out-of-range confidence"),
    ],
)
def test_provider_evaluation_rejects_invalid_structured_fields(
    provider_responses: dict[str, object], change, description: str
) -> None:
    payload = copy.deepcopy(provider_responses["valid_evaluation"])
    change(payload)

    with pytest.raises(ValidationError):
        ProviderEvaluation.model_validate(payload)


def test_provider_evaluation_rejects_evidence_absent_from_input_transcript(
    provider_responses: dict[str, object], evaluation_request: EvaluationRequest
) -> None:
    payload = copy.deepcopy(provider_responses["valid_evaluation"])
    payload["evidence"] = ["不存在于输入对话中的证据"]

    with pytest.raises(ValueError, match="evidence"):
        parse_evaluation_response(payload, evaluation_request)


def test_attribution_parser_accepts_a_json_root_cause(
    evaluation_request: EvaluationRequest,
) -> None:
    request = AttributionRequest(
        conversation=evaluation_request.conversation,
        evaluation=parse_evaluation_response(
            {
                "dimensions": {
                    "correctness": 90,
                    "completeness": 80,
                    "relevance": 85,
                    "service_experience": 88,
                    "compliance": 100,
                },
                "reason": "客服说明了退款处理时效。",
                "evidence": ["退款将在三个工作日内原路退回"],
                "confidence": 0.92,
            },
            evaluation_request,
        ),
    )

    result = parse_attribution_response(
        {
            "root_cause": "other",
            "reason": "需要人工确认具体根因。",
            "evidence": ["退款将在三个工作日内原路退回"],
            "confidence": 0.8,
        },
        request,
    )

    assert result.root_cause.value == "other"


@pytest.mark.parametrize(
    "fixture_name", ["malformed_evaluation", "truncated_evaluation", "non_json_evaluation"]
)
def test_provider_response_fixtures_fail_explicitly(
    provider_responses: dict[str, object], evaluation_request: EvaluationRequest, fixture_name: str
) -> None:
    with pytest.raises((ProviderResponseFormatError, ValidationError)):
        parse_evaluation_response(provider_responses[fixture_name], evaluation_request)


def test_fake_provider_is_deterministic_for_the_same_redacted_conversation(
    evaluation_request: EvaluationRequest,
) -> None:
    provider = FakeEvaluationProvider()

    first = provider.evaluate(evaluation_request)
    second = provider.evaluate(evaluation_request)
    attribution = provider.attribute(
        AttributionRequest(conversation=evaluation_request.conversation, evaluation=first)
    )
    draft = provider.draft_qa(
        QADraftRequest(conversation=evaluation_request.conversation, attribution=attribution)
    )

    assert isinstance(provider, EvaluationProvider)
    assert first == second
    assert first.evidence[0] in "\n".join(
        message.content for message in evaluation_request.conversation.messages
    )
    assert attribution.evidence[0] == first.evidence[0]
    assert draft.evidence[0] == first.evidence[0]
