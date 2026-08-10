from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.evaluation.openai_compatible import (
    ModelProviderError,
    build_evaluation_provider,
    provider_is_configured,
)
from app.evaluation.providers import EvaluationProvider
from app.remediation.export import InvalidQAState, export_qa
from app.remediation.service import (
    AttributionCommand,
    approve_qa,
    confirm_attribution,
    generate_qa_draft,
    generate_qa_for_task,
    list_qa_workspace,
    qa_workspace_detail,
    reject_qa,
)
from app.shared.enums import RootCause

router = APIRouter(tags=["remediation"])


def get_remediation_provider() -> EvaluationProvider:
    if not provider_is_configured(settings):
        raise HTTPException(status_code=503, detail="真实模型尚未配置")
    return build_evaluation_provider(settings)


class _StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AttributionConfirmationBody(_StrictBody):
    actor: str = Field(min_length=1)
    root_cause: RootCause = Field(strict=False)
    member_ids: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(min_length=1)
    bulk: bool = False
    confirm_cluster: bool = False


class QAApprovalBody(_StrictBody):
    actor: str = Field(min_length=1)
    edits: dict[str, Any] | None = None


class QAExportBody(_StrictBody):
    actor: str = Field(min_length=1)
    draft_ids: list[str] = Field(min_length=1)
    format: Literal["csv", "json"]


class QARejectionBody(_StrictBody):
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class TaskResponse(_StrictBody):
    id: str | None
    type: str | None


class QADraftResponse(_StrictBody):
    id: str
    status: str
    current_version_number: int


@router.get("/api/qa-workspace")
def get_qa_workspace(
    session: Annotated[Session, Depends(get_session)],
    status: Literal["pending", "approved", "rejected", "all"] = Query(default="pending"),
) -> dict[str, Any]:
    return list_qa_workspace(session, status)


@router.get("/api/qa-workspace/{task_id}")
def get_qa_workspace_detail(
    task_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict[str, Any]:
    try:
        return qa_workspace_detail(session, task_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/api/qa-workspace/{task_id}/generate", response_model=QADraftResponse)
def generate_workspace_qa_draft(
    task_id: str,
    session: Annotated[Session, Depends(get_session)],
    provider: Annotated[EvaluationProvider, Depends(get_remediation_provider)],
) -> QADraftResponse:
    try:
        draft = generate_qa_for_task(session, task_id, provider)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ModelProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return QADraftResponse(
        id=draft.id,
        status=draft.status.value,
        current_version_number=draft.current_version_number,
    )


@router.post("/api/badcases/{cluster_id}/confirm-attribution", response_model=TaskResponse)
def confirm_cluster_attribution(
    cluster_id: str,
    body: AttributionConfirmationBody,
    session: Annotated[Session, Depends(get_session)],
) -> TaskResponse:
    try:
        task = confirm_attribution(
            session,
            AttributionCommand(
                cluster_id=cluster_id,
                actor=body.actor,
                root_cause=body.root_cause,
                member_ids=tuple(body.member_ids),
                evidence=tuple(body.evidence),
                bulk=body.bulk,
                confirm_cluster=body.confirm_cluster,
            ),
        )
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return TaskResponse(id=task.id if task else None, type=task.type.value if task else None)


@router.post("/api/badcases/{cluster_id}/qa-drafts", response_model=QADraftResponse)
def create_qa_draft(
    cluster_id: str,
    session: Annotated[Session, Depends(get_session)],
    provider: Annotated[EvaluationProvider, Depends(get_remediation_provider)],
) -> QADraftResponse:
    try:
        draft = generate_qa_draft(session, cluster_id, provider)
    except ModelProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return QADraftResponse(
        id=draft.id,
        status=draft.status.value,
        current_version_number=draft.current_version_number,
    )


@router.post("/api/qa-drafts/{draft_id}/approve")
def approve_draft(
    draft_id: str,
    body: QAApprovalBody,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, int | str]:
    try:
        version = approve_qa(session, draft_id, body.actor, body.edits)
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"id": version.id, "version_number": version.version_number}


@router.post("/api/qa-drafts/{draft_id}/reject")
def reject_draft(
    draft_id: str,
    body: QARejectionBody,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str]:
    try:
        draft = reject_qa(session, draft_id, body.actor, body.reason)
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"id": draft.id, "status": draft.status.value}


@router.post("/api/qa-exports")
def create_qa_export(
    body: QAExportBody,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    try:
        artifact = export_qa(session, body.draft_ids, body.format, body.actor)
    except (LookupError, InvalidQAState, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "id": artifact.record.id,
        "path": artifact.record.artifact_path,
        "metadata": artifact.metadata,
    }


@router.post("/api/qa-exports/download")
def download_qa_export(
    body: QAExportBody,
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    try:
        artifact = export_qa(session, body.draft_ids, body.format, body.actor)
    except (LookupError, InvalidQAState, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return Response(
        content=artifact.content,
        media_type=artifact.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="qa-export.{body.format}"',
            "X-Export-ID": artifact.record.id,
        },
    )
