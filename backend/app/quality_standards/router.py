from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.quality_standards.contracts import QualityStandardRules
from app.quality_standards.documents import MAX_DOCUMENT_SIZE
from app.quality_standards.parser import StandardParseTransport
from app.quality_standards.provider import OpenAICompatibleStandardTransport
from app.quality_standards.service import (
    PublishedStandardError,
    QualityStandardError,
    create_standard,
    delete_standard,
    get_standard,
    list_standards,
    parse_standard_draft,
    publish_standard,
    standard_payload,
    update_standard_draft,
)

router = APIRouter(prefix="/api/quality-standards", tags=["quality-standards"])


def get_standard_parse_transport() -> StandardParseTransport:
    return OpenAICompatibleStandardTransport(settings)


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_standard(
    file: Annotated[UploadFile, File()], session: Annotated[Session, Depends(get_session)]
) -> dict[str, Any]:
    try:
        content = await _read_limited(file)
        standard = create_standard(
            session, settings.quality_standard_storage_dir, file.filename or "", content
        )
        return standard_payload(standard)
    except (QualityStandardError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("")
def get_standards(session: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    payload = []
    for item in list_standards(session):
        published = None
        published_rules = None
        for version in sorted(
            item.versions, key=lambda value: value.version_number, reverse=True
        ):
            if version.published_at is None:
                continue
            try:
                published_rules = QualityStandardRules.model_validate(version.rules).model_dump(
                    mode="json"
                )
            except ValueError:
                continue
            published = version
            break
        payload.append({
            "id": item.id,
            "name": item.name,
            "status": item.status,
            "latest_version": max((version.version_number for version in item.versions), default=0),
            "published_version_id": published.id if published else None,
            "published_rules": published_rules,
            "updated_at": item.updated_at.isoformat(),
        })
    return payload


@router.get("/{standard_id}")
def get_standard_detail(
    standard_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict[str, Any]:
    try:
        return standard_payload(get_standard(session, standard_id))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/{standard_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_standard(
    standard_id: str, session: Annotated[Session, Depends(get_session)]
) -> Response:
    try:
        delete_standard(session, settings.quality_standard_storage_dir, standard_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PublishedStandardError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{standard_id}/parse")
def parse_uploaded_standard(
    standard_id: str,
    session: Annotated[Session, Depends(get_session)],
    transport: Annotated[StandardParseTransport, Depends(get_standard_parse_transport)],
) -> dict[str, Any]:
    try:
        return standard_payload(
            parse_standard_draft(
                session, settings.quality_standard_storage_dir, standard_id, transport
            )
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PublishedStandardError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (QualityStandardError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.put("/{standard_id}/draft")
def save_standard_draft(
    standard_id: str,
    rules: QualityStandardRules,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    try:
        return standard_payload(update_standard_draft(session, standard_id, rules))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PublishedStandardError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/{standard_id}/publish")
def publish_standard_draft(
    standard_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict[str, Any]:
    try:
        return standard_payload(publish_standard(session, standard_id))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PublishedStandardError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (QualityStandardError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


async def _read_limited(file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(min(1024 * 1024, MAX_DOCUMENT_SIZE + 1 - size)):
        chunks.append(chunk)
        size += len(chunk)
        if size > MAX_DOCUMENT_SIZE:
            raise QualityStandardError("单个文件不能超过 20 MB，请拆分后再上传")
    return b"".join(chunks)
