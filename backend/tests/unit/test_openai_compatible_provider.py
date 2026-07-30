from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from app.evaluation.contracts import EvaluationRequest
from app.evaluation.openai_compatible import ModelProviderError, OpenAICompatibleTransport
from app.ingestion.contracts import Message, NormalizedConversation


def _request() -> EvaluationRequest:
    return EvaluationRequest(
        conversation=NormalizedConversation(
            external_id="dialog-1",
            scenario="refund",
            status=None,
            occurred_at=datetime(2026, 7, 30, tzinfo=UTC),
            messages=(Message(role="user", content="手机号 [PHONE]"),),
        )
    )


def _settings(api_key: str = "secret-key") -> SimpleNamespace:
    return SimpleNamespace(
        llm_base_url="https://models.example/v1",
        llm_api_key=api_key,
        llm_model="judge-model",
        llm_timeout_seconds=30.0,
    )


def test_openai_transport_posts_redacted_transcript_and_parses_json() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        content = {
            "dimensions": {
                "correctness": 90,
                "completeness": 80,
                "relevance": 85,
                "service_experience": 75,
                "compliance": 100,
            },
            "reason": "回答基本正确",
            "evidence": ["手机号 [PHONE]"],
            "confidence": 0.9,
            "severe_factual_error": False,
            "severe_compliance_error": False,
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(content)}}]},
        )

    transport = OpenAICompatibleTransport(
        _settings(), httpx.Client(transport=httpx.MockTransport(handler))
    )
    result = transport.evaluate(_request())

    assert result.dimensions["correctness"] == 90
    payload = json.loads(captured[0].content)
    assert payload["model"] == "judge-model"
    assert "[PHONE]" in captured[0].content.decode()
    assert "13800138000" not in captured[0].content.decode()


def test_provider_error_never_contains_api_key() -> None:
    api_key = "never-leak-this-key"
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(401)))
    transport = OpenAICompatibleTransport(_settings(api_key), client)

    with pytest.raises(ModelProviderError) as error:
        transport.evaluate(_request())

    assert api_key not in str(error.value)
