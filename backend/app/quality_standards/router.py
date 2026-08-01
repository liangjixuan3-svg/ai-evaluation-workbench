from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.quality_standards.documents import MAX_DOCUMENT_SIZE
from app.quality_standards.service import (
    PublishedStandardError,
    QualityStandardError,
    create_standard,
    delete_standard,
    get_standard,
    list_standards,
    standard_payload,
)

router = APIRouter(prefix="/api/quality-standards", tags=["quality-standards"])


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
    return [
        {
            "id": item.id,
            "name": item.name,
            "status": item.status,
            "latest_version": max((version.version_number for version in item.versions), default=0),
            "updated_at": item.updated_at.isoformat(),
        }
        for item in list_standards(session)
    ]


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


async def _read_limited(file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(min(1024 * 1024, MAX_DOCUMENT_SIZE + 1 - size)):
        chunks.append(chunk)
        size += len(chunk)
        if size > MAX_DOCUMENT_SIZE:
            raise QualityStandardError("单个文件不能超过 20 MB，请拆分后再上传")
    return b"".join(chunks)
