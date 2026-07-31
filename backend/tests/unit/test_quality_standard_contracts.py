from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.quality_standards.contracts import QualityStandardRules


def _valid_rule(*, effect: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "id": "correctness-refund-policy",
        "title": "Refund policy accuracy",
        "requirement": "Explain the approved refund policy without inventing exceptions.",
        "dimension": "correctness",
        "effect": effect or {"kind": "normal"},
        "source_quote": "Refunds require documented approval.",
        "source_locator": "Section 3.2",
        "confidence": 0.95,
        "confirmed": True,
    }


def _valid_rules(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "threshold": 80,
        "weights": {
            "correctness": 0.30,
            "completeness": 0.20,
            "relevance": 0.20,
            "service_experience": 0.15,
            "compliance": 0.15,
        },
        "anchors": [
            {"level": "excellent", "description": "Consistently exceeds the standard."},
            {"level": "good", "description": "Meets the standard with minor gaps."},
            {"level": "acceptable", "description": "Satisfies the minimum standard."},
            {"level": "poor", "description": "Falls short in material ways."},
            {"level": "unacceptable", "description": "Does not satisfy the standard."},
        ],
        "common_rules": [_valid_rule()],
        "scenarios": [{"name": "Refund request", "rules": [_valid_rule()]}],
    }
    payload.update(overrides)
    return payload


def test_accepts_complete_rules_with_all_fixed_dimensions_and_supported_effects() -> None:
    rules = QualityStandardRules.model_validate(
        _valid_rules(
            common_rules=[
                _valid_rule(),
                _valid_rule(effect={"kind": "dimension_cap", "dimension_cap": 60}),
                _valid_rule(effect={"kind": "veto"}),
            ]
        )
    )

    assert set(rules.weights) == {
        "correctness",
        "completeness",
        "relevance",
        "service_experience",
        "compliance",
    }
    assert rules.common_rules[1].effect.dimension_cap == 60


def test_rejects_weights_that_do_not_sum_to_one() -> None:
    invalid = _valid_rules(
        weights={
            "correctness": 0.40,
            "completeness": 0.20,
            "relevance": 0.20,
            "service_experience": 0.15,
            "compliance": 0.15,
        }
    )

    with pytest.raises(ValidationError, match="权重之和必须为 1"):
        QualityStandardRules.model_validate(invalid)


@pytest.mark.parametrize(
    "weights",
    [
        {
            "correctness": 0.25,
            "completeness": 0.20,
            "relevance": 0.20,
            "service_experience": 0.20,
            "compliance": 0.15,
            "safety": 0.0,
        },
        {
            "correctness": 0.35,
            "completeness": 0.20,
            "relevance": 0.20,
            "service_experience": 0.15,
        },
    ],
)
def test_rejects_unknown_or_missing_fixed_dimensions(weights: dict[str, float]) -> None:
    with pytest.raises(ValidationError, match="五个固定维度"):
        QualityStandardRules.model_validate(_valid_rules(weights=weights))


def test_rejects_rule_without_source_traceability() -> None:
    rule = _valid_rule()
    rule["source_quote"] = ""

    with pytest.raises(ValidationError):
        QualityStandardRules.model_validate(_valid_rules(common_rules=[rule]))


@pytest.mark.parametrize("cap", [-1, 101])
def test_rejects_dimension_cap_outside_score_range(cap: int) -> None:
    with pytest.raises(ValidationError, match="维度上限必须在 0 到 100 之间"):
        QualityStandardRules.model_validate(
            _valid_rules(common_rules=[_valid_rule(effect={"kind": "dimension_cap", "dimension_cap": cap})])
        )


def test_rejects_blank_scenario_name() -> None:
    with pytest.raises(ValidationError):
        QualityStandardRules.model_validate(
            _valid_rules(scenarios=[{"name": "   ", "rules": [_valid_rule()]}])
        )
