from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db import get_session
from app.evaluation_prompts.service import (
    PromptVersionConflict,
    PromptVersionError,
    create_prompt_draft,
    delete_prompt_draft,
    list_prompt_versions,
    prompt_payload,
    publish_prompt_draft,
    update_prompt_draft,
)

router = APIRouter(prefix="/api/evaluation-prompts", tags=["evaluation-prompts"])


class CopyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str


class UpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(max_length=20_000)


@router.get("")
def get_prompts(session: Annotated[Session, Depends(get_session)]) -> list[dict]:
    return [prompt_payload(prompt) for prompt in list_prompt_versions(session)]


@router.post("/drafts", status_code=status.HTTP_201_CREATED)
def copy_prompt(
    body: CopyBody, session: Annotated[Session, Depends(get_session)]
) -> dict:
    return _handle(lambda: prompt_payload(create_prompt_draft(session, body.source_id)))


@router.put("/{prompt_id}")
def save_prompt(
    prompt_id: str, body: UpdateBody, session: Annotated[Session, Depends(get_session)]
) -> dict:
    return _handle(
        lambda: prompt_payload(update_prompt_draft(session, prompt_id, body.content))
    )


@router.delete("/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prompt(
    prompt_id: str, session: Annotated[Session, Depends(get_session)]
) -> Response:
    _handle(lambda: delete_prompt_draft(session, prompt_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{prompt_id}/publish")
def publish_prompt(
    prompt_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict:
    return _handle(lambda: prompt_payload(publish_prompt_draft(session, prompt_id)))


def _handle(action):
    try:
        return action()
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PromptVersionConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except PromptVersionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
