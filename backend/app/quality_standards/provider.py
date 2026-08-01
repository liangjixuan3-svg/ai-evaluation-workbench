from __future__ import annotations

import json
from typing import Protocol

import httpx

from app.quality_standards.documents import SourceSection


class LLMSettings(Protocol):
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_seconds: float


SYSTEM_PROMPT = """你是公司客服质量标准结构化助手。根据文档提取可执行评测规则，只返回一个 JSON 对象。必须包含 threshold、weights、anchors、common_rules、scenarios。weights 必须且只能包含 correctness、completeness、relevance、service_experience、compliance，合计为 1。anchors 必须包含 excellent、good、acceptable、poor、unacceptable 五档。每条规则包含 id、title、requirement、dimension、effect、source_quote、source_locator、confidence、confirmed；effect.kind 只能是 normal、dimension_cap、veto，普通规则的 dimension_cap 为 null。source_quote 必须逐字引用输入原文，confirmed 固定为 false。无法判断时使用默认阈值 75 和五维各 0.2。"""


class OpenAICompatibleStandardTransport:
    def __init__(self, settings: LLMSettings, client: httpx.Client | None = None) -> None:
        if not standard_provider_is_configured(settings):
            raise ValueError("真实模型尚未配置")
        self.settings = settings
        self.client = client or httpx.Client()

    def parse(self, sections: list[SourceSection]) -> dict:
        payload = {
            "model": self.settings.llm_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps([
                    {"locator": item.locator, "text": item.text} for item in sections
                ], ensure_ascii=False)},
            ],
        }
        try:
            response = self.client.post(
                f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                json=payload,
                timeout=self.settings.llm_timeout_seconds,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"模型接口返回 HTTP {response.status_code}")
            content = response.json()["choices"][0]["message"]["content"]
            result = json.loads(content)
            if not isinstance(result, dict):
                raise TypeError("模型没有返回 JSON 对象")
            return result
        except RuntimeError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError(f"质量标准解析失败：{type(error).__name__}") from error


def standard_provider_is_configured(settings: LLMSettings) -> bool:
    return bool(
        settings.llm_base_url.strip()
        and settings.llm_api_key.strip()
        and settings.llm_model.strip()
    )
