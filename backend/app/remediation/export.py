from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.remediation.models import ExportRecord, QADraft, QAExportItem, QAVersion
from app.shared.audit import record_audit

CSV_HEADER = (
    "draft_id",
    "version_number",
    "question",
    "answer",
    "applicability",
    "handling_steps",
    "estimated_time",
    "escalation",
)
EXPORT_SCHEMA_VERSION = "qa-export-v1"


class InvalidQAState(ValueError):
    pass


class UnsupportedExportFormat(ValueError):
    pass


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class QAExportItemDocument(_StrictModel):
    draft_id: str
    version_number: int
    question: str
    answer: str
    applicability: str
    handling_steps: list[str]
    estimated_time: str
    escalation: str


class QAExportDocument(_StrictModel):
    schema_version: Literal["qa-export-v1"]
    items: list[QAExportItemDocument]


@dataclass(frozen=True, slots=True)
class ExportArtifact:
    record: ExportRecord
    content: bytes
    media_type: str
    metadata: dict[str, str | int]


def export_qa(
    session: Session, draft_ids: list[str], format: str, actor: str = "system"
) -> ExportArtifact:
    """Export the current approved version of every requested draft exactly once."""
    export_format = _validated_format(format)
    drafts = _approved_drafts(session, draft_ids)
    document = QAExportDocument(
        schema_version=EXPORT_SCHEMA_VERSION,
        items=[_document_item(draft, draft.current_version) for draft in drafts],
    )
    content, media_type = _serialize(document, export_format)
    artifact_hash = hashlib.sha256(content).hexdigest()
    metadata: dict[str, str | int] = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "format": export_format,
        "encoding": "utf-8",
        "item_count": len(document.items),
        "sha256": artifact_hash,
    }

    record = session.scalar(
        select(ExportRecord)
        .where(ExportRecord.format == export_format, ExportRecord.artifact_hash == artifact_hash)
        .with_for_update()
    )
    if record is None:
        record = ExportRecord(
            format=export_format,
            created_by=actor,
            artifact_path=f"qa-exports/{artifact_hash}.{export_format}",
            artifact_hash=artifact_hash,
            status="ready",
        )
        try:
            with session.begin_nested():
                session.add(record)
                session.flush()
                session.add_all(
                    QAExportItem(export_id=record.id, qa_version_id=draft.current_version.id)
                    for draft in drafts
                )
                record_audit(
                    session,
                    actor=actor,
                    action="qa_exported",
                    entity_type="export_record",
                    entity_id=record.id,
                    payload={"evidence": [], "metadata": metadata, "draft_ids": sorted(draft_ids)},
                )
        except IntegrityError:
            record = session.scalar(
                select(ExportRecord)
                .where(
                    ExportRecord.format == export_format,
                    ExportRecord.artifact_hash == artifact_hash,
                )
                .with_for_update()
            )
            if record is None:
                raise
    session.commit()
    return ExportArtifact(record=record, content=content, media_type=media_type, metadata=metadata)


def _validated_format(format: str) -> Literal["csv", "json"]:
    if format not in {"csv", "json"}:
        raise UnsupportedExportFormat("format must be csv or json")
    return format  # type: ignore[return-value]


def _approved_drafts(session: Session, draft_ids: list[str]) -> list[QADraft]:
    requested_ids = sorted(set(draft_ids))
    if not requested_ids:
        raise InvalidQAState("at least one draft must be exported")
    drafts = list(
        session.scalars(select(QADraft).where(QADraft.id.in_(requested_ids)).order_by(QADraft.id))
    )
    if len(drafts) != len(requested_ids):
        raise LookupError("one or more QA drafts do not exist")
    if any(draft.current_version.approved_at is None for draft in drafts):
        raise InvalidQAState("only approved QA versions can be exported")
    return drafts


def _document_item(draft: QADraft, version: QAVersion) -> QAExportItemDocument:
    content = version.content
    return QAExportItemDocument(
        draft_id=draft.id,
        version_number=version.version_number,
        question=content["question"],
        answer=content["answer"],
        applicability=content["applicability"],
        handling_steps=content["handling_steps"],
        estimated_time=content["estimated_time"],
        escalation=content["escalation"],
    )


def _serialize(
    document: QAExportDocument, export_format: Literal["csv", "json"]
) -> tuple[bytes, str]:
    if export_format == "json":
        return (
            json.dumps(
                document.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8"),
            "application/json",
        )
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for item in document.items:
        writer.writerow(
            [
                item.draft_id,
                item.version_number,
                item.question,
                item.answer,
                item.applicability,
                json.dumps(item.handling_steps, ensure_ascii=False, separators=(",", ":")),
                item.estimated_time,
                item.escalation,
            ]
        )
    return output.getvalue().encode("utf-8"), "text/csv"
