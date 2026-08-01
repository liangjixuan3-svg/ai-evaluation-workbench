from __future__ import annotations

import pytest

from app.quality_standards.documents import SourceSection
from app.quality_standards.parser import parse_standard


def _payload(quote: str, confidence: float = 0.9) -> dict:
    return {
        "threshold": 80,
        "weights": {
            "correctness": 0.3,
            "completeness": 0.2,
            "relevance": 0.2,
            "service_experience": 0.15,
            "compliance": 0.15,
        },
        "anchors": [
            {"level": "excellent", "description": "完全符合"},
            {"level": "good", "description": "基本符合"},
            {"level": "acceptable", "description": "勉强可用"},
            {"level": "poor", "description": "明显不足"},
            {"level": "unacceptable", "description": "不可接受"},
        ],
        "common_rules": [{
            "id": "rule-1", "title": "告知时效", "requirement": "必须告知处理时效",
            "dimension": "completeness", "effect": {"kind": "normal", "dimension_cap": None},
            "source_quote": quote, "source_locator": "第 1 段", "confidence": confidence,
            "confirmed": True,
        }],
        "scenarios": [],
    }


class Transport:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def parse(self, sections) -> dict:
        return self.payload


def test_parser_requires_human_confirmation_for_ai_rules() -> None:
    rules = parse_standard(
        [SourceSection(locator="第 1 段", text="客服必须告知处理时效。")],
        Transport(_payload("必须告知处理时效")),
    )

    assert rules.threshold == 80
    assert rules.common_rules[0].confirmed is False


def test_parser_rejects_quote_not_found_in_document() -> None:
    with pytest.raises(ValueError, match="引用未在原文中找到"):
        parse_standard(
            [SourceSection(locator="第 1 段", text="客服必须告知处理时效。")],
            Transport(_payload("不存在的原文")),
        )
