from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.quality_standards.documents import extract_document
from app.quality_standards.models import (
    QualityStandard,
    QualityStandardParseJob,
    QualityStandardVersion,
)
from app.quality_standards.storage import delete_document, store_document


class QualityStandardError(ValueError):
    pass


class PublishedStandardError(QualityStandardError):
    pass


def create_standard(
    session: Session, storage_dir: Path, filename: str, content: bytes
) -> QualityStandard:
    safe_filename = Path(filename).name.strip()
    if not safe_filename:
        raise QualityStandardError("文件名不能为空")
    extracted = extract_document(safe_filename, content)
    existing = session.scalar(
        select(QualityStandard)
        .join(QualityStandardVersion)
        .where(QualityStandardVersion.source_sha256 == extracted.sha256)
        .options(
            selectinload(QualityStandard.versions),
            selectinload(QualityStandard.parse_jobs),
        )
    )
    if existing is not None:
        return existing

    path, created = store_document(storage_dir, extracted.sha256, Path(safe_filename).suffix, content)
    standard = QualityStandard(name=Path(safe_filename).stem[:128], status="draft")
    standard.versions.append(
        QualityStandardVersion(
            version_number=1,
            source_filename=safe_filename,
            source_sha256=extracted.sha256,
            source_path=str(path),
            rules=_initial_rules(),
        )
    )
    standard.parse_jobs.append(QualityStandardParseJob(status="queued"))
    session.add(standard)
    try:
        session.commit()
    except Exception:
        session.rollback()
        if created:
            delete_document(path, storage_dir)
        raise
    return standard


def list_standards(session: Session) -> list[QualityStandard]:
    return list(
        session.scalars(
            select(QualityStandard)
            .options(selectinload(QualityStandard.versions))
            .order_by(QualityStandard.updated_at.desc(), QualityStandard.id)
        )
    )


def get_standard(session: Session, standard_id: str) -> QualityStandard:
    standard = session.scalar(
        select(QualityStandard)
        .where(QualityStandard.id == standard_id)
        .options(
            selectinload(QualityStandard.versions),
            selectinload(QualityStandard.parse_jobs),
        )
    )
    if standard is None:
        raise LookupError("质量标准不存在")
    return standard


def delete_standard(session: Session, storage_dir: Path, standard_id: str) -> None:
    standard = get_standard(session, standard_id)
    if standard.status == "published" or any(
        version.published_at is not None for version in standard.versions
    ):
        raise PublishedStandardError("已发布的质量标准不能删除")
    paths = [Path(version.source_path) for version in standard.versions]
    session.delete(standard)
    session.commit()
    for path in paths:
        delete_document(path, storage_dir)


def standard_payload(standard: QualityStandard) -> dict[str, Any]:
    versions = sorted(standard.versions, key=lambda item: item.version_number)
    jobs = sorted(standard.parse_jobs, key=lambda item: item.created_at)
    draft = next((item for item in reversed(versions) if item.published_at is None), None)
    return {
        "id": standard.id,
        "name": standard.name,
        "status": standard.status,
        "updated_at": standard.updated_at.isoformat(),
        "draft": _version_payload(draft) if draft else None,
        "versions": [_version_payload(version) for version in versions],
        "parse_jobs": [
            {
                "id": job.id,
                "status": job.status,
                "error_summary": job.error_summary,
                "attempts": job.attempts,
            }
            for job in jobs
        ],
    }


def _version_payload(version: QualityStandardVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "version_number": version.version_number,
        "source_filename": version.source_filename,
        "rules": version.rules,
        "published_at": version.published_at.isoformat() if version.published_at else None,
    }


def _initial_rules() -> dict[str, Any]:
    return {
        "threshold": 75,
        "weights": {
            "correctness": 0.2,
            "completeness": 0.2,
            "relevance": 0.2,
            "service_experience": 0.2,
            "compliance": 0.2,
        },
        "anchors": [
            {"level": "excellent", "description": "完全满足质量要求"},
            {"level": "good", "description": "满足主要要求，仅有轻微不足"},
            {"level": "acceptable", "description": "基本可用，但需要改进"},
            {"level": "poor", "description": "未解决主要问题"},
            {"level": "unacceptable", "description": "完全不符合质量要求"},
        ],
        "common_rules": [],
        "scenarios": [],
    }
