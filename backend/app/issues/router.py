from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.issues.service import issue_detail, list_issues

router = APIRouter(prefix="/api/issues", tags=["issues"])


@router.get("")
def get_issues(
    session: Annotated[Session, Depends(get_session)],
    status: Literal["pending", "confirmed", "all"] = Query(default="all"),
) -> dict:
    return list_issues(session, status)


@router.get("/{cluster_id}")
def get_issue(
    cluster_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict:
    try:
        return issue_detail(session, cluster_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
