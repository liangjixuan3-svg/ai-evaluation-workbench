from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Protocol

from app.evaluation.contracts import EVALUATION_DIMENSIONS, EvaluationOutcome, ProviderEvaluation


class EvaluationTemplateLike(Protocol):
    weights: Mapping[str, object]
    threshold: object


def calculate_outcome(
    provider_result: ProviderEvaluation, template: EvaluationTemplateLike
) -> EvaluationOutcome:
    weights = template.weights
    if not weights:
        raise ValueError("template weights must not be empty")

    unknown_dimensions = frozenset(weights) - EVALUATION_DIMENSIONS
    if unknown_dimensions:
        raise ValueError(f"template contains unknown dimension: {sorted(unknown_dimensions)}")

    score = sum(
        Decimal(str(provider_result.dimensions[dimension])) * _as_decimal(weight, "weight")
        for dimension, weight in weights.items()
    )
    threshold = _as_decimal(template.threshold, "threshold")
    if not Decimal(0) <= threshold <= Decimal(100):
        raise ValueError("threshold must be between 0 and 100")

    vetoed = provider_result.severe_factual_error or provider_result.severe_compliance_error
    return EvaluationOutcome(score=round(float(score), 2), passed=not vetoed and score >= threshold)


def _as_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be numeric")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field_name} must be numeric") from error
