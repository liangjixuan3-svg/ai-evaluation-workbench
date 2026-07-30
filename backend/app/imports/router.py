from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db import get_session
from app.imports.contracts import ImportMapping
from app.imports.service import (
    ImportErrorBase,
    InvalidImportState,
    abandon_import,
    candidate_payloads,
    confirm_import,
    create_import_session,
    list_confirmed_imports,
    preview_import,
)

router = APIRouter(prefix="/api/imports", tags=["imports"])


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UploadBody(StrictBody):
    filename: str = Field(min_length=1, max_length=255)
    document: Any


class PreviewBody(StrictBody):
    mapping: ImportMapping
    timezone_name: str = "Asia/Shanghai"
    error_policy: Literal["block", "skip"] = "block"


class ConfirmBody(StrictBody):
    source_name: str = Field(min_length=1, max_length=128)
    actor: str = Field(min_length=1, max_length=128)


@router.post("/json", status_code=status.HTTP_201_CREATED)
def upload_json(
    body: UploadBody, session: Annotated[Session, Depends(get_session)]
) -> dict[str, Any]:
    try:
        imported = create_import_session(session, body.filename, body.document)
    except ImportErrorBase as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "id": imported.id,
        "filename": imported.filename,
        "status": imported.status,
        "record_count": imported.record_count,
        "candidates": candidate_payloads(imported),
    }


@router.get("")
def get_imports(
    session: Annotated[Session, Depends(get_session)], status: str = "confirmed"
) -> list[dict[str, Any]]:
    if status != "confirmed":
        raise HTTPException(status_code=422, detail="only confirmed imports can be listed")
    return list_confirmed_imports(session)


@router.post("/{import_id}/preview")
def create_preview(
    import_id: str,
    body: PreviewBody,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    try:
        result, items = preview_import(
            session, import_id, body.mapping, body.timezone_name, body.error_policy
        )
    except (ImportErrorBase, LookupError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "valid_count": len(result.items),
        "error_count": len(result.errors),
        "errors": [
            {"row_index": error.row_index, "message": error.message} for error in result.errors
        ],
        "items": items,
    }


@router.post("/{import_id}/confirm")
def confirm_json_import(
    import_id: str,
    body: ConfirmBody,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str | int]:
    try:
        return confirm_import(session, import_id, body.source_name, body.actor).as_dict()
    except (ImportErrorBase, InvalidImportState, LookupError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.delete("/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_import(import_id: str, session: Annotated[Session, Depends(get_session)]) -> Response:
    try:
        abandon_import(session, import_id)
    except InvalidImportState as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
