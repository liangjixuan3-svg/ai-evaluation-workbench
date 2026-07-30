from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.imports.contracts import ImportMapping, NormalizationResult
from app.imports.models import ImportSession
from app.imports.parser import (
    discover_record_arrays,
    normalize_records,
    read_record_array,
    suggest_mapping,
)
from app.ingestion.models import Conversation, DataSource
from app.ingestion.redaction import redact_text
from app.ingestion.service import ingest_conversations
from app.shared.audit import record_audit
from app.shared.types import utc_now

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
IMPORT_TTL = timedelta(hours=24)


class ImportErrorBase(ValueError):
    pass


class ImportLimitError(ImportErrorBase):
    pass


class InvalidImportState(ImportErrorBase):
    pass


@dataclass(frozen=True, slots=True)
class ConfirmedImport:
    import_id: str
    source_id: str
    inserted: int
    skipped: int
    errors: int
    available_count: int

    def as_dict(self) -> dict[str, str | int]:
        return {
            "import_id": self.import_id,
            "source_id": self.source_id,
            "inserted": self.inserted,
            "skipped": self.skipped,
            "errors": self.errors,
            "available_count": self.available_count,
        }


def create_import_session(session: Session, filename: str, document: Any) -> ImportSession:
    cleanup_expired_imports(session)
    encoded = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_DOCUMENT_BYTES:
        raise ImportLimitError("JSON 文件不能超过 20 MB")
    candidates = discover_record_arrays(document)
    if not candidates:
        raise ImportErrorBase("JSON 中没有找到对话记录数组")
    file_hash = sha256(encoded).hexdigest()
    existing = session.scalar(select(ImportSession).where(ImportSession.file_hash == file_hash))
    if existing is not None:
        return existing
    safe_filename = Path(filename).name.strip()[:255]
    if not safe_filename:
        raise ImportErrorBase("文件名不能为空")
    import_session = ImportSession(
        filename=safe_filename,
        file_hash=file_hash,
        status="uploaded",
        document=document,
        candidate_paths=[candidate.path for candidate in candidates],
        record_count=candidates[0].length,
        expires_at=utc_now() + IMPORT_TTL,
    )
    session.add(import_session)
    session.commit()
    return import_session


def candidate_payloads(import_session: ImportSession) -> list[dict[str, Any]]:
    candidates = discover_record_arrays(import_session.document)
    payloads: list[dict[str, Any]] = []
    for candidate in candidates:
        suggested = suggest_mapping(candidate.sample).model_copy(
            update={"record_path": candidate.path}
        )
        payloads.append(
            {
                "path": candidate.path,
                "length": candidate.length,
                "object_ratio": candidate.object_ratio,
                "sample": list(candidate.sample),
                "suggested_mapping": suggested.model_dump(),
            }
        )
    return payloads


def preview_import(
    session: Session,
    import_id: str,
    mapping: ImportMapping,
    timezone_name: str,
    error_policy: str,
) -> tuple[NormalizationResult, list[dict[str, Any]]]:
    import_session = session.get(ImportSession, import_id)
    _require_editable(import_session)
    stored_mapping = mapping.model_copy(
        update={"timezone_name": timezone_name, "error_policy": error_policy}
    )
    result = normalize_records(
        import_session.document,
        stored_mapping,
        timezone_name,
        error_policy,
    )
    import_session.mapping = stored_mapping.model_dump()
    import_session.error_count = len(result.errors)
    import_session.status = "previewed"
    records = read_record_array(import_session.document, stored_mapping.record_path)
    previews = []
    for item in result.items[:10]:
        messages = item.body["messages"]
        previews.append(
            {
                "external_id": item.external_id,
                "scenario": item.scenario,
                "status": item.status,
                "occurred_at": item.occurred_at.isoformat(),
                "raw": item.body["raw"],
                "normalized_messages": messages,
                "redacted_messages": [
                    {"role": message["role"], "content": redact_text(message["content"])}
                    for message in messages
                ],
            }
        )
    import_session.record_count = len(records)
    session.commit()
    return result, previews


def confirm_import(
    session: Session, import_id: str, source_name: str, actor: str
) -> ConfirmedImport:
    import_session = session.scalar(
        select(ImportSession).where(ImportSession.id == import_id).with_for_update()
    )
    if import_session is None:
        raise LookupError("导入会话不存在")
    if import_session.status == "confirmed":
        return ConfirmedImport(**import_session.result_summary)
    _require_editable(import_session)
    if import_session.status != "previewed" or not import_session.mapping:
        raise InvalidImportState("请先生成并确认字段映射预览")
    if not source_name.strip() or not actor.strip():
        raise ImportErrorBase("数据源名称和操作人不能为空")
    mapping = ImportMapping.model_validate(import_session.mapping)
    result = normalize_records(
        import_session.document,
        mapping,
        mapping.timezone_name,
        mapping.error_policy,
    )
    if not result.items:
        raise InvalidImportState("没有可写入的有效对话")
    source = DataSource(
        name=source_name.strip(),
        kind="json_upload",
        config={"file_hash": import_session.file_hash, "import_id": import_session.id},
    )
    session.add(source)
    try:
        session.flush()
    except IntegrityError as error:
        session.rollback()
        raise ImportErrorBase("数据源名称已存在") from error
    summary = ingest_conversations(session, source.id, list(result.items), commit=False)
    confirmed = ConfirmedImport(
        import_id=import_session.id,
        source_id=source.id,
        inserted=summary.inserted,
        skipped=summary.skipped,
        errors=len(result.errors),
        available_count=summary.inserted,
    )
    import_session.status = "confirmed"
    import_session.confirmed_source_id = source.id
    import_session.confirmed_at = utc_now()
    import_session.result_summary = confirmed.as_dict()
    record_audit(
        session,
        actor=actor.strip(),
        action="json_import_confirmed",
        entity_type="import_session",
        entity_id=import_session.id,
        payload={
            "filename": import_session.filename,
            "file_hash": import_session.file_hash,
            "mapping": import_session.mapping,
            **confirmed.as_dict(),
        },
    )
    session.commit()
    return confirmed


def list_confirmed_imports(session: Session) -> list[dict[str, Any]]:
    cleanup_expired_imports(session)
    rows = list(
        session.scalars(
            select(ImportSession)
            .where(ImportSession.status == "confirmed")
            .order_by(ImportSession.confirmed_at.desc())
        )
    )
    return [
        {
            "id": item.id,
            "filename": item.filename,
            "source_id": item.confirmed_source_id,
            "available_count": int(
                session.scalar(
                    select(func.count(Conversation.id)).where(
                        Conversation.data_source_id == item.confirmed_source_id
                    )
                )
                or 0
            ),
            "confirmed_at": item.confirmed_at.isoformat() if item.confirmed_at else None,
        }
        for item in rows
    ]


def abandon_import(session: Session, import_id: str) -> None:
    import_session = session.get(ImportSession, import_id)
    if import_session is None:
        return
    if import_session.status == "confirmed":
        raise InvalidImportState("已确认的导入记录不能删除")
    session.delete(import_session)
    session.commit()


def cleanup_expired_imports(session: Session) -> None:
    session.execute(
        delete(ImportSession).where(
            ImportSession.status != "confirmed", ImportSession.expires_at < utc_now()
        )
    )
    session.commit()


def _require_editable(import_session: ImportSession | None) -> None:
    if import_session is None:
        raise LookupError("导入会话不存在")
    if import_session.status == "confirmed":
        raise InvalidImportState("导入会话已经确认")
    if import_session.expires_at < utc_now():
        raise InvalidImportState("导入会话已过期，请重新上传")
