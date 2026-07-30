from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dashboard.service import get_workbench_summary
from app.db import get_session

router = APIRouter(tags=["workbench"])


@router.get("/api/workbench")
def get_workbench(session: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    return get_workbench_summary(session)
