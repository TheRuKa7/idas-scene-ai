"""Stream CRUD + start/stop.

``POST /streams/{id}/start`` hands the stream over to the global
:class:`RunnerRegistry`, which instantiates a :class:`StreamRunner`, kicks
off the ffmpeg frame source, and begins publishing alerts on the
:class:`AlertBus`. ``stop`` is the inverse. Both are idempotent — calling
``start`` on a running stream or ``stop`` on an idle one returns 200 with
the current state.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from idas.api.deps import get_db_session, get_runner_registry, get_stream_repo
from idas.api.runner_registry import RunnerRegistry
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
    registry: Annotated[RunnerRegistry, Depends(get_runner_registry)],
) -> None:
    # Stop the runner first — deleting the spec while a runner is live would
    # leave a zombie task publishing alerts for a stream that no longer exists.
    await registry.stop(stream_id)
    if not repo.delete(session, stream_id):
        raise HTTPException(status_code=404, detail="stream not found")


# ---- lifecycle ----------------------------------------------------------------


@router.post("/{stream_id}/start", response_model=Stream)
async def start_stream(
    stream_id: str,
    session: Annotated[Session, Depends(get_db_session)],
    repo: Annotated[StreamRepo, Depends(get_stream_repo)],
    registry: Annotated[RunnerRegistry, Depends(get_runner_registry)],
) -> Stream:
    stream = repo.get(session, stream_id)
    if stream is None:
        raise HTTPException(status_code=404, detail="stream not found")
    try:
        await registry.start(stream_id)
    except KeyError:  # pragma: no cover — race with DELETE
        raise HTTPException(status_code=404, detail="stream vanished")
    # Re-read so we return the updated state.
    updated = repo.get(session, stream_id)
    assert updated is not None
    return updated


@router.post("/{stream_id}/stop", response_model=Stream)
async def stop_stream(
    stream_id: str,
    session: Annotated[Session, Depends(get_db_session)],
    repo: Annotated[StreamRepo, Depends(get_stream_repo)],
    registry: Annotated[RunnerRegistry, Depends(get_runner_registry)],
) -> Stream:
    stream = repo.get(session, stream_id)
    if stream is None:
        raise HTTPException(status_code=404, detail="stream not found")
    await registry.stop(stream_id)
    # The runner sets state=stopped in its cancel handler, but that write is
    # async — force the state here so the response is correct even on races.
    repo.set_state(session, stream_id, state="stopped")
    updated = repo.get(session, stream_id)
    assert updated is not None
    return updated
