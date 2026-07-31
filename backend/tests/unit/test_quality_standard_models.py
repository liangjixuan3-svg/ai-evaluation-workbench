from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.quality_standards.models import QualityStandard, QualityStandardVersion
from app.shared.types import ImmutableRecordError


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
                rules={},
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
