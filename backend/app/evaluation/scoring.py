from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Protocol

from app.evaluation.contracts import (
    EVALUATION_DIMENSIONS,
    EvaluationOutcome,
    ProviderEvaluation,
)

WEIGHT_TOLERANCE = Decimal("0.000001")


class EvaluationTemplateLike(Protocol):
    weights: Mapping[str, object]
    threshold: object


def calculate_outcome(
    provider_result: ProviderEvaluation, template: EvaluationTemplateLike
) -> EvaluationOutcome:
    weights = template.weights
    if not weights:
        raise ValueError("template weights must not be empty")

    actual_dimensions = frozenset(weights)
    unknown_dimensions = actual_dimensions - EVALUATION_DIMENSIONS
    if unknown_dimensions:
        raise ValueError(f"template contains unknown dimension: {sorted(unknown_dimensions)}")
    missing_dimensions = EVALUATION_DIMENSIONS - actual_dimensions
    if missing_dimensions:
        raise ValueError(f"template weights missing dimensions: {sorted(missing_dimensions)}")

    normalized_weights = {
        dimension: _validate_weight(weights[dimension]) for dimension in EVALUATION_DIMENSIONS
    }
    if abs(sum(normalized_weights.values()) - Decimal(1)) > WEIGHT_TOLERANCE:
        raise ValueError("template weights must sum to 1")

    score = sum(
        Decimal(str(provider_result.dimensions[dimension])) * normalized_weights[dimension]
        for dimension in EVALUATION_DIMENSIONS
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
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field_name} must be numeric") from error
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


def _validate_weight(value: object) -> Decimal:
    weight = _as_decimal(value, "weights")
    if not Decimal(0) <= weight <= Decimal(1):
        raise ValueError("template weights must be between 0 and 1")
    return weight
