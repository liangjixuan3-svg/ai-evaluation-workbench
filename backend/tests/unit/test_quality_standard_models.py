from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.quality_standards.models import QualityStandard, QualityStandardVersion
from app.shared.types import ImmutableRecordError


def _valid_rules() -> dict[str, object]:
    rule = {
        "id": "correctness-refund-policy",
        "title": "Refund policy accuracy",
        "requirement": "Explain the approved refund policy.",
        "dimension": "correctness",
        "effect": {"kind": "normal"},
        "source_quote": "Refunds require documented approval.",
        "source_locator": "Section 3.2",
        "confidence": 0.95,
        "confirmed": True,
    }
    return {
        "threshold": 80,
        "weights": {
            "correctness": 0.30,
            "completeness": 0.20,
            "relevance": 0.20,
            "service_experience": 0.15,
            "compliance": 0.15,
        },
        "anchors": [
            {"level": "excellent", "description": "Excellent"},
            {"level": "good", "description": "Good"},
            {"level": "acceptable", "description": "Acceptable"},
            {"level": "poor", "description": "Poor"},
            {"level": "unacceptable", "description": "Unacceptable"},
        ],
        "common_rules": [rule],
        "scenarios": [{"name": "Refund request", "rules": [rule]}],
    }


def test_allows_draft_edits_and_publication_but_freezes_published_versions() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            standard = QualityStandard(name="Customer service")
            version = QualityStandardVersion(
                standard=standard,
                version_number=1,
                source_filename="standard.docx",
                source_sha256="a" * 64,
                source_path="quality-standards/standard.docx",
                rules=_valid_rules(),
            )
            session.add(version)
            session.commit()

            version.source_path = "quality-standards/revised-standard.docx"
            session.commit()

            version.published_at = datetime(2026, 7, 31, tzinfo=UTC)
            session.commit()

            version.source_path = "quality-standards/changed-after-publishing.docx"
            with pytest.raises(ImmutableRecordError):
                session.commit()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "invalid_rules",
    [
        {},
        {
            **_valid_rules(),
            "weights": {
                "correctness": 0.50,
                "completeness": 0.20,
                "relevance": 0.20,
                "service_experience": 0.15,
                "compliance": 0.15,
            },
        },
        {**_valid_rules(), "common_rules": [{"id": "missing-source-and-effect"}]},
    ],
)
def test_rejects_invalid_rules_when_assigned_to_version(invalid_rules: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        QualityStandardVersion(
            standard_id="00000000-0000-0000-0000-000000000001",
            version_number=1,
            source_filename="standard.docx",
            source_sha256="a" * 64,
            source_path="quality-standards/standard.docx",
            rules=invalid_rules,
        )


def test_revalidates_rules_before_insert() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            standard = QualityStandard(name="Invalid rules boundary")
            version = QualityStandardVersion(
                standard=standard,
                version_number=1,
                source_filename="standard.docx",
                source_sha256="a" * 64,
                source_path="quality-standards/standard.docx",
                rules=_valid_rules(),
            )
            version.__dict__["rules"] = {}
            session.add(version)

            with pytest.raises(ValueError):
                session.flush()
    finally:
        engine.dispose()


def test_normalizes_valid_rules_on_assignment() -> None:
    version = QualityStandardVersion(
        standard_id="00000000-0000-0000-0000-000000000001",
        version_number=1,
        source_filename="standard.docx",
        source_sha256="a" * 64,
        source_path="quality-standards/standard.docx",
        rules=_valid_rules(),
    )

    assert version.rules["common_rules"][0]["dimension"] == "correctness"
