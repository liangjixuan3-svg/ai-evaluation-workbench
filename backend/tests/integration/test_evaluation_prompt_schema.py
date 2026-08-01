from sqlalchemy import create_engine, inspect

from app.db import Base
from app.evaluation.models import PromptVersion
from app.quality_standards.models import QualityStandardVersion


def test_prompt_versions_include_publication_time() -> None:
    assert PromptVersion.__tablename__ == "prompt_versions"
    assert QualityStandardVersion.__tablename__ == "quality_standard_versions"
    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(engine)
        columns = {column["name"]: column for column in inspect(engine).get_columns("prompt_versions")}
        assert columns["published_at"]["nullable"] is True
    finally:
        engine.dispose()
