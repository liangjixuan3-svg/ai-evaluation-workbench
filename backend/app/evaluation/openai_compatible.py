from __future__ import annotations

import json
from typing import Any, Protocol

import httpx

from app.evaluation.contracts import (
    AttributionRequest,
    EvaluationRequest,
    ProviderAttribution,
    ProviderEvaluation,
    ProviderQADraft,
    QADraftRequest,
)
from app.evaluation.providers import (
    EvaluationProvider,
    FakeEvaluationProvider,
    ProviderIdentity,
    parse_attribution_response,
    parse_evaluation_response,
    parse_qa_draft_response,
)

EVALUATION_SYSTEM_PROMPT = """你是客服质量评测员。只返回一个 JSON 对象，包含 dimensions（correctness、completeness、relevance、service_experience、compliance，均为 0-100）、reason、evidence、confidence、severe_factual_error、severe_compliance_error。evidence 必须是字符串数组，数组内容必须逐字引用输入对话；confidence 必须是 0-1 之间的小数。"""
ATTRIBUTION_SYSTEM_PROMPT = """你是客服问题归因助手。只返回一个 JSON 对象，包含 root_cause（missing_knowledge、misunderstanding、process_failure、service_tone、other）、reason、evidence、confidence。evidence 必须是字符串数组，数组内容必须逐字引用输入对话；confidence 必须是 0-1 之间的小数。"""
QA_SYSTEM_PROMPT = """你是客服知识库编辑。只返回一个 JSON 对象，包含 content（question、answer、applicability、handling_steps、estimated_time、escalation）、reason、evidence、confidence。evidence 必须是字符串数组，数组内容必须逐字引用输入对话；confidence 必须是 0-1 之间的小数。"""

class LLMSettings(Protocol):
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_seconds: float


class ModelProviderError(RuntimeError):
    pass


class OpenAICompatibleTransport:
    def __init__(self, settings: LLMSettings, client: httpx.Client | None = None) -> None:
        if not provider_is_configured(settings):
            raise ValueError("真实模型尚未配置")
        self._settings = settings
        self._client = client or httpx.Client()
        self.identity = ProviderIdentity(provider="openai-compatible", model=settings.llm_model)

    def evaluate(self, request: EvaluationRequest) -> ProviderEvaluation:
        content = self._request(
            EVALUATION_SYSTEM_PROMPT,
            {"conversation": _conversation_payload(request.conversation)},
        )
        return parse_evaluation_response(_normalize_provider_content(content), request)

    def attribute(self, request: AttributionRequest) -> ProviderAttribution:
        content = self._request(
            ATTRIBUTION_SYSTEM_PROMPT,
            {
                "conversation": _conversation_payload(request.conversation),
                "evaluation": request.evaluation.model_dump(),
            },
        )
        return parse_attribution_response(_normalize_provider_content(content), request)

    def draft_qa(self, request: QADraftRequest) -> ProviderQADraft:
        content = self._request(
            QA_SYSTEM_PROMPT,
            {
                "conversation": _conversation_payload(request.conversation),
                "attribution": request.attribution.model_dump(mode="json"),
            },
        )
        return parse_qa_draft_response(_normalize_provider_content(content), request)

    def _request(self, system_prompt: str, input_payload: dict[str, Any]) -> str:
        payload = {
            "model": self._settings.llm_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(input_payload, ensure_ascii=False),
                },
            ],
        }
        try:
            response = self._client.post(
                f"{self._settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self._settings.llm_api_key}"},
                json=payload,
                timeout=self._settings.llm_timeout_seconds,
            )
            if response.status_code >= 400:
                raise ModelProviderError(f"模型接口返回 HTTP {response.status_code}")
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ModelProviderError("模型响应缺少文本内容")
            return content
        except ModelProviderError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise ModelProviderError(f"模型调用失败：{type(error).__name__}") from error


def provider_is_configured(settings: LLMSettings) -> bool:
    return bool(
        settings.llm_base_url.strip()
        and settings.llm_api_key.strip()
        and settings.llm_model.strip()
    )


def build_evaluation_provider(settings: LLMSettings) -> EvaluationProvider:
    if not provider_is_configured(settings):
        return FakeEvaluationProvider()
    return EvaluationProvider(OpenAICompatibleTransport(settings))


def _normalize_provider_content(content: str) -> str | dict[str, Any]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return content
    if not isinstance(data, dict):
        return content

    if isinstance(data.get("evidence"), str):
        data["evidence"] = [data["evidence"]]

    confidence = data.get("confidence")
    if (
        isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and 1 < confidence <= 100
    ):
        data["confidence"] = confidence / 100
    return data


def _conversation_payload(conversation: Any) -> dict[str, Any]:
    return {
        "external_id": conversation.external_id,
        "scenario": conversation.scenario,
        "messages": [
            {"role": message.role, "content": message.content} for message in conversation.messages
        ],
    }
