from __future__ import annotations

from typing import Protocol

from app.quality_standards.contracts import QualityStandardRules
from app.quality_standards.documents import SourceSection


class StandardParseTransport(Protocol):
    def parse(self, sections: list[SourceSection]) -> dict: ...


def parse_standard(
    sections: list[SourceSection], transport: StandardParseTransport
) -> QualityStandardRules:
    rules = QualityStandardRules.model_validate(transport.parse(sections))
    source = "\n".join(section.text for section in sections)
    seen: set[tuple[str, str]] = set()

    def validate_rule(rule):
        if rule.source_quote not in source:
            raise ValueError(f"规则“{rule.title}”的引用未在原文中找到")
        rule.confirmed = False
        return rule

    common = []
    for rule in rules.common_rules:
        key = (rule.title, rule.requirement)
        if key not in seen:
            seen.add(key)
            common.append(validate_rule(rule))
    rules.common_rules = common
    for scenario in rules.scenarios:
        unique = []
        for rule in scenario.rules:
            key = (rule.title, rule.requirement)
            if key not in seen:
                seen.add(key)
                unique.append(validate_rule(rule))
        scenario.rules = unique
    return rules
