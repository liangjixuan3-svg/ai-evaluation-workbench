from __future__ import annotations

from enum import StrEnum
from math import isclose
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class QualityDimension(StrEnum):
    CORRECTNESS = "correctness"
    COMPLETENESS = "completeness"
    RELEVANCE = "relevance"
    SERVICE_EXPERIENCE = "service_experience"
    COMPLIANCE = "compliance"


class RuleEffectKind(StrEnum):
    NORMAL = "normal"
    DIMENSION_CAP = "dimension_cap"
    VETO = "veto"


class RuleEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: RuleEffectKind
    dimension_cap: int | None = None

    @model_validator(mode="after")
    def validate_dimension_cap(self) -> RuleEffect:
        if self.kind is RuleEffectKind.DIMENSION_CAP:
            if self.dimension_cap is None or not 0 <= self.dimension_cap <= 100:
                raise ValueError("维度上限必须在 0 到 100 之间")
        elif self.dimension_cap is not None:
            raise ValueError("只有维度上限规则可以设置 dimension_cap")
        return self


class QualityStandardRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    requirement: str
    dimension: QualityDimension
    effect: RuleEffect
    source_quote: str
    source_locator: str
    confidence: float
    confirmed: bool

    @field_validator("id", "title", "requirement", "source_quote", "source_locator")
    @classmethod
    def require_non_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("规则文本不能为空")
        return value

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("置信度必须在 0 到 1 之间")
        return value


class QualityStandardAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["excellent", "good", "acceptable", "poor", "unacceptable"]
    description: str

    @field_validator("description")
    @classmethod
    def require_non_blank_description(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("评分锚点说明不能为空")
        return value


class QualityStandardScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    rules: list[QualityStandardRule]

    @field_validator("name")
    @classmethod
    def require_non_blank_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("场景名称不能为空")
        return value


class QualityStandardRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: float
    weights: dict[QualityDimension, float]
    anchors: list[QualityStandardAnchor]
    common_rules: list[QualityStandardRule]
    scenarios: list[QualityStandardScenario]

    @model_validator(mode="before")
    @classmethod
    def validate_fixed_dimension_keys(cls, value: object) -> object:
        if not isinstance(value, dict) or not isinstance(value.get("weights"), dict):
            return value
        expected = {item.value for item in QualityDimension}
        if set(value["weights"]) != expected:
            raise ValueError("权重必须且只能包含五个固定维度")
        return value

    @model_validator(mode="after")
    def validate_rule_set(self) -> QualityStandardRules:
        if not 0 <= self.threshold <= 100:
            raise ValueError("通过阈值必须在 0 到 100 之间")
        if not isclose(sum(self.weights.values()), 1, rel_tol=0, abs_tol=1e-9):
            raise ValueError("权重之和必须为 1")
        expected_levels = {"excellent", "good", "acceptable", "poor", "unacceptable"}
        if len(self.anchors) != 5 or {anchor.level for anchor in self.anchors} != expected_levels:
            raise ValueError("评分锚点必须完整覆盖五档")
        return self
