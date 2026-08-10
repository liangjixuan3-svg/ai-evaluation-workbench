from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.shared.enums import CalibrationDimension


class _StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AgreeReviewInput(_StrictBody):
    actor: str = Field(min_length=1, max_length=128)

    @field_validator("actor", mode="before")
    @classmethod
    def strip_actor(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            raise ValueError("actor is required")
        return value


class DisagreeReviewInput(AgreeReviewInput):
    corrected_passed: bool
    disagreement_dimension: CalibrationDimension = Field(strict=False)
    review_basis: str = Field(min_length=1, max_length=1000)

    @field_validator("review_basis", mode="before")
    @classmethod
    def strip_review_basis(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            raise ValueError("review_basis is required")
        return value
