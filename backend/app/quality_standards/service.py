from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.quality_standards.contracts import QualityStandardRules
from app.quality_standards.documents import extract_document
from app.quality_standards.models import (
    QualityStandard,
    QualityStandardParseJob,
    QualityStandardVersion,
)
from app.quality_standards.parser import StandardParseTransport, parse_standard
from app.quality_standards.storage import (
    delete_document,
    read_document,
    restore_document,
    store_document,
)
from app.shared.types import utc_now


class QualityStandardError(ValueError):
    pass


class PublishedStandardError(QualityStandardError):
    pass


def parse_standard_draft(
    session: Session,
    storage_dir: Path,
    standard_id: str,
    transport: StandardParseTransport,
) -> QualityStandard:
    standard = get_standard(session, standard_id)
    draft = _draft_version(standard)
    if draft is None:
        raise PublishedStandardError("该标准没有可解析的草稿")
    job = max(standard.parse_jobs, key=lambda item: item.created_at, default=None)
    if job is None:
        job = QualityStandardParseJob(status="queued")
        standard.parse_jobs.append(job)
    job.status = "running"
    job.attempts += 1
    job.error_summary = None
    session.commit()
    try:
        content = read_document(Path(draft.source_path), storage_dir)
        extracted = extract_document(draft.source_filename, content)
        rules = parse_standard(extracted.sections, transport)
        draft.rules = rules.model_dump(mode="json")
        job.status = "completed"
        standard.updated_at = utc_now()
        session.commit()
    except Exception as error:
        session.rollback()
        failed_job = session.get(QualityStandardParseJob, job.id)
        if failed_job is not None:
            failed_job.status = "failed"
            failed_job.error_summary = str(error)[:1000]
            session.commit()
        raise QualityStandardError(f"解析失败：{error}") from error
    return get_standard(session, standard_id)


def update_standard_draft(
    session: Session, standard_id: str, rules: QualityStandardRules
) -> QualityStandard:
    standard = get_standard(session, standard_id)
    draft = _draft_version(standard)
    if draft is None:
        raise PublishedStandardError("已发布标准不能直接修改，请创建新版本")
    draft.rules = rules.model_dump(mode="json")
    standard.updated_at = utc_now()
    session.commit()
    return get_standard(session, standard_id)


def publish_standard(session: Session, standard_id: str) -> QualityStandard:
    standard = get_standard(session, standard_id)
    draft = _draft_version(standard)
    if draft is None:
        raise PublishedStandardError("该标准没有可发布的草稿")
    rules = QualityStandardRules.model_validate(draft.rules)
    pending = [
        rule.title
        for rule in [
            *rules.common_rules,
            *(rule for scenario in rules.scenarios for rule in scenario.rules),
        ]
        if not rule.confirmed
    ]
    if pending:
        raise QualityStandardError(f"还有 {len(pending)} 条规则未人工确认")
    draft.published_at = utc_now()
    standard.status = "published"
    standard.updated_at = utc_now()
    session.commit()
    return get_standard(session, standard_id)


def create_standard(
    session: Session, storage_dir: Path, filename: str, content: bytes
) -> QualityStandard:
    safe_filename = Path(filename).name.strip()
    if not safe_filename:
        raise QualityStandardError("文件名不能为空")
    extracted = extract_document(safe_filename, content)
    existing = _standard_by_hash(session, extracted.sha256)
    if existing is not None:
        return existing

    path, created = store_document(storage_dir, extracted.sha256, Path(safe_filename).suffix, content)
    base_name = Path(safe_filename).stem[:128]
    name = _available_name(session, base_name, extracted.sha256)
    try:
        return _persist_standard(session, name, safe_filename, extracted.sha256, path)
    except IntegrityError:
        session.rollback()
        existing = _standard_by_hash(session, extracted.sha256)
        if existing is not None:
            return existing
        retry_name = f"{base_name[:119]}-{extracted.sha256[:8]}"
        try:
            return _persist_standard(
                session, retry_name, safe_filename, extracted.sha256, path
            )
        except Exception:
            session.rollback()
            if created:
                delete_document(path, storage_dir)
            raise
    except Exception:
        session.rollback()
        if created:
            delete_document(path, storage_dir)
        raise


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
    backups = [
        (Path(version.source_path), read_document(Path(version.source_path), storage_dir))
        for version in standard.versions
    ]
    deleted: list[tuple[Path, bytes]] = []
    try:
        for path, content in backups:
            delete_document(path, storage_dir)
            deleted.append((path, content))
        session.delete(standard)
        session.commit()
    except Exception:
        session.rollback()
        for path, content in deleted:
            restore_document(path, content)
        raise


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


def _draft_version(standard: QualityStandard) -> QualityStandardVersion | None:
    return next(
        (
            item
            for item in sorted(standard.versions, key=lambda value: value.version_number, reverse=True)
            if item.published_at is None
        ),
        None,
    )


def _standard_by_hash(session: Session, file_hash: str) -> QualityStandard | None:
    return session.scalar(
        select(QualityStandard)
        .join(QualityStandardVersion)
        .where(QualityStandardVersion.source_sha256 == file_hash)
        .options(
            selectinload(QualityStandard.versions),
            selectinload(QualityStandard.parse_jobs),
        )
    )


def _available_name(session: Session, base_name: str, file_hash: str) -> str:
    exists = session.scalar(select(QualityStandard.id).where(QualityStandard.name == base_name))
    if exists is None:
        return base_name
    return f"{base_name[:119]}-{file_hash[:8]}"


def _persist_standard(
    session: Session, name: str, filename: str, file_hash: str, path: Path
) -> QualityStandard:
    standard = QualityStandard(name=name, status="draft")
    standard.versions.append(
        QualityStandardVersion(
            version_number=1,
            source_filename=filename,
            source_sha256=file_hash,
            upload_dedup_key=file_hash,
            source_path=str(path),
            rules=_initial_rules(),
        )
    )
    standard.parse_jobs.append(QualityStandardParseJob(status="queued"))
    session.add(standard)
    session.commit()
    return standard


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
