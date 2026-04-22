"""Alerts = persisted rule hits. Mobile reads this."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from idas.api.deps import get_db_session, get_hit_repo
from idas.models.schemas import RuleHit
from idas.storage.repos import RuleHitRepo

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[RuleHit])
async def list_alerts(
    session: Annotated[Session, Depends(get_db_session)],
    repo: Annotated[RuleHitRepo, Depends(get_hit_repo)],
    stream_id: str | None = Query(None, description="filter to a single stream"),
    limit: int = Query(100, ge=1, le=1000),
) -> list[RuleHit]:
    if stream_id:
        return repo.list_for_stream(session, stream_id, limit=limit)
    return repo.list_recent(session, limit=limit)
