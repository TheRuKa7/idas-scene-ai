"""Stream CRUD + start/stop."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from idas.api.deps import get_db_session, get_stream_repo
from idas.models.schemas import Stream, StreamCreate
from idas.storage.repos import StreamRepo

router = APIRouter(prefix="/streams", tags=["streams"])


@router.post("", response_model=Stream, status_code=status.HTTP_201_CREATED)
async def create_stream(
    spec: StreamCreate,
    session: Annotated[Session, Depends(get_db_session)],
    repo: Annotated[StreamRepo, Depends(get_stream_repo)],
) -> Stream:
    stream_id = uuid.uuid4().hex[:16]
    return repo.create(session, spec, stream_id)


@router.get("", response_model=list[Stream])
async def list_streams(
    session: Annotated[Session, Depends(get_db_session)],
    repo: Annotated[StreamRepo, Depends(get_stream_repo)],
) -> list[Stream]:
    return repo.list(session)


@router.get("/{stream_id}", response_model=Stream)
async def get_stream(
    stream_id: str,
    session: Annotated[Session, Depends(get_db_session)],
    repo: Annotated[StreamRepo, Depends(get_stream_repo)],
) -> Stream:
    stream = repo.get(session, stream_id)
    if stream is None:
        raise HTTPException(status_code=404, detail="stream not found")
    return stream


@router.delete("/{stream_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stream(
    stream_id: str,
    session: Annotated[Session, Depends(get_db_session)],
    repo: Annotated[StreamRepo, Depends(get_stream_repo)],
) -> None:
    if not repo.delete(session, stream_id):
        raise HTTPException(status_code=404, detail="stream not found")


# NOTE: POST /streams/{id}/start + stop live here too once we wire the runner
# registry in a later pass; the runner itself is already implemented in
# idas.pipeline.runner. Keeping the routes minimal lets us ship the API
# surface without a global runner registry.
