from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_session
from app.main import create_app
from app.quality_standards.models import (
    QualityStandard,
    QualityStandardParseJob,
    QualityStandardVersion,
)
from app.quality_standards.storage import delete_document


def _docx_bytes(text: str = "客服回复必须准确且完整。") -> bytes:
    document = Document()
    document.add_paragraph(text)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(settings, "quality_standard_storage_dir", tmp_path / "standards")
    app = create_app()

    def override_session():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, sessions
    engine.dispose()


def test_upload_is_idempotent_and_exposes_draft_without_paths(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = api
    content = _docx_bytes()

    first = client.post(
        "/api/quality-standards",
        files={"file": ("../制度/客服标准.docx", content, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    second = client.post(
        "/api/quality-standards",
        files={"file": ("renamed.docx", content, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    payload = first.json()
    assert payload["status"] == "draft"
    assert payload["draft"]["version_number"] == 1
    assert payload["draft"]["source_filename"] == "客服标准.docx"
    assert payload["draft"]["rules"]["threshold"] == 75
    assert payload["parse_jobs"][0]["status"] == "queued"
    assert "source_path" not in str(payload)
    assert str(settings.quality_standard_storage_dir) not in str(payload)

    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(QualityStandard)) == 1
        assert session.scalar(select(func.count()).select_from(QualityStandardVersion)) == 1
        assert session.scalar(select(func.count()).select_from(QualityStandardParseJob)) == 1
    stored_files = [path for path in settings.quality_standard_storage_dir.rglob("*") if path.is_file()]
    assert len(stored_files) == 1
    assert "客服标准.docx" not in stored_files[0].name


def test_list_detail_and_delete_draft_cleanup_file(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = api
    uploaded = client.post(
        "/api/quality-standards",
        files={"file": ("standard.docx", _docx_bytes(), "application/octet-stream")},
    ).json()

    listed = client.get("/api/quality-standards")
    detail = client.get(f"/api/quality-standards/{uploaded['id']}")

    assert listed.status_code == 200
    assert listed.json() == [
        {
            "id": uploaded["id"],
            "name": "standard",
            "status": "draft",
            "latest_version": 1,
            "updated_at": uploaded["updated_at"],
        }
    ]
    assert detail.status_code == 200
    assert detail.json()["draft"]["id"] == uploaded["draft"]["id"]
    assert detail.json()["versions"][0]["version_number"] == 1
    assert detail.json()["parse_jobs"][0]["status"] == "queued"

    deleted = client.delete(f"/api/quality-standards/{uploaded['id']}")

    assert deleted.status_code == 204
    assert not settings.quality_standard_storage_dir.exists()
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(QualityStandard)) == 0


def test_same_filename_with_different_content_gets_a_distinct_name(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = api

    first = client.post(
        "/api/quality-standards",
        files={"file": ("客服标准.docx", _docx_bytes("第一版"), "application/octet-stream")},
    )
    second = client.post(
        "/api/quality-standards",
        files={"file": ("客服标准.docx", _docx_bytes("第二版"), "application/octet-stream")},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["name"] == "客服标准"
    assert second.json()["name"].startswith("客服标准-")


def test_delete_published_standard_returns_conflict_and_preserves_file(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = api
    uploaded = client.post(
        "/api/quality-standards",
        files={"file": ("published.docx", _docx_bytes(), "application/octet-stream")},
    ).json()
    with sessions() as session:
        standard = session.get(QualityStandard, uploaded["id"])
        version = session.get(QualityStandardVersion, uploaded["draft"]["id"])
        assert standard is not None and version is not None
        standard.status = "published"
        version.published_at = datetime.now(UTC)
        session.commit()

    response = client.delete(f"/api/quality-standards/{uploaded['id']}")

    assert response.status_code == 409
    assert "已发布" in response.json()["detail"]
    assert any(settings.quality_standard_storage_dir.rglob("*"))


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("standard.txt", b"plain text", "仅支持 .docx 和 .pdf"),
        ("broken.pdf", b"%PDF-1.4\n%%EOF", "PDF 文档无法读取"),
        pytest.param(
            "oversize.pdf",
            b"x" * (20 * 1024 * 1024 + 1),
            "不能超过 20 MB",
            id="oversize-pdf",
        ),
    ],
)
def test_upload_validation_errors_are_chinese_422(
    api: tuple[TestClient, sessionmaker[Session]],
    filename: str,
    content: bytes,
    message: str,
) -> None:
    client, sessions = api

    response = client.post(
        "/api/quality-standards",
        files={"file": (filename, content, "application/octet-stream")},
    )

    assert response.status_code == 422
    assert message in response.json()["detail"]
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(QualityStandard)) == 0
    assert not settings.quality_standard_storage_dir.exists()


def test_database_failure_removes_new_file_and_rolls_back_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    monkeypatch.setattr(settings, "quality_standard_storage_dir", tmp_path / "standards")
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    original_commit = session.commit

    def fail_commit() -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(session, "commit", fail_commit)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/quality-standards",
            files={"file": ("standard.docx", _docx_bytes(), "application/octet-stream")},
        )

    assert response.status_code == 500
    assert not settings.quality_standard_storage_dir.exists()
    monkeypatch.setattr(session, "commit", original_commit)
    session.rollback()
    assert session.scalar(select(func.count()).select_from(QualityStandard)) == 0
    session.close()
    engine.dispose()


def test_file_delete_failure_preserves_database_and_file(
    api: tuple[TestClient, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, sessions = api
    uploaded = client.post(
        "/api/quality-standards",
        files={"file": ("standard.docx", _docx_bytes(), "application/octet-stream")},
    ).json()

    def fail_delete(path: Path, storage_dir: Path) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr("app.quality_standards.service.delete_document", fail_delete)
    response = client.delete(f"/api/quality-standards/{uploaded['id']}")

    assert response.status_code == 500
    with sessions() as session:
        assert session.get(QualityStandard, uploaded["id"]) is not None
    assert any(settings.quality_standard_storage_dir.rglob("*"))


def test_delete_document_rejects_paths_outside_storage(tmp_path: Path) -> None:
    storage_dir = tmp_path / "standards"
    storage_dir.mkdir()
    outside = tmp_path / "outside.docx"
    outside.write_bytes(b"keep")

    with pytest.raises(ValueError, match="不在质量标准存储目录"):
        delete_document(outside, storage_dir)

    assert outside.read_bytes() == b"keep"


def test_delete_document_rejects_symlink_escape(tmp_path: Path) -> None:
    storage_dir = tmp_path / "standards"
    storage_dir.mkdir()
    outside = tmp_path / "outside.docx"
    outside.write_bytes(b"keep")
    symlink = storage_dir / "linked.docx"
    symlink.symlink_to(outside)

    with pytest.raises(ValueError, match="不在质量标准存储目录"):
        delete_document(symlink, storage_dir)

    assert outside.read_bytes() == b"keep"
