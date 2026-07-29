from __future__ import annotations

from decimal import Decimal

import pytest

from app.evaluation.contracts import ProviderEvaluation
from app.evaluation.models import EvaluationTemplate
from app.evaluation.scoring import calculate_outcome


def _template(*, threshold: str = "80.00") -> EvaluationTemplate:
    return EvaluationTemplate(
        name="quality",
        version="1",
        weights={
            "correctness": 0.4,
            "completeness": 0.2,
            "relevance": 0.15,
            "service_experience": 0.15,
            "compliance": 0.1,
        },
        threshold=Decimal(threshold),
        veto_rules={},
    )


def _result(**changes: object) -> ProviderEvaluation:
    values: dict[str, object] = {
        "dimensions": {
            "correctness": 90,
            "completeness": 80,
            "relevance": 70,
            "service_experience": 60,
            "compliance": 100,
        },
        "reason": "客服给出了完整的退款说明。",
        "evidence": ["退款将在三个工作日内原路退回"],
        "confidence": 0.9,
    }
    values.update(changes)
    return ProviderEvaluation(**values)


def test_weighted_score_uses_template_weights_and_threshold() -> None:
    outcome = calculate_outcome(_result(), _template())

    assert outcome.score == 81.5
    assert outcome.passed is True


def test_compliance_veto_fails_even_with_high_weighted_score() -> None:
    result = _result(
        dimensions={
            "correctness": 95,
            "completeness": 95,
            "relevance": 95,
            "service_experience": 95,
            "compliance": 20,
        },
        severe_compliance_error=True,
    )

    assert calculate_outcome(result, _template()).passed is False


def test_factual_veto_fails_even_when_weighted_score_meets_threshold() -> None:
    result = _result(
        dimensions={
            "correctness": 95,
            "completeness": 95,
            "relevance": 95,
            "service_experience": 95,
            "compliance": 95,
        },
        severe_factual_error=True,
    )

    assert calculate_outcome(result, _template()).passed is False


def test_scoring_rejects_a_template_weight_for_an_unknown_dimension() -> None:
    template = _template()
    template.weights = {"invented": 1}

    with pytest.raises(ValueError, match="unknown dimension"):
        calculate_outcome(_result(), template)
