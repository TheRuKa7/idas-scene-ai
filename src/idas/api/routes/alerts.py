"""Alerts = persisted rule hits, plus a live SSE feed."""
from __future__ import annotations

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from idas.api.alert_bus import AlertBus
from idas.api.deps import get_alert_bus, get_db_session, get_hit_repo
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


# ---- live SSE feed ------------------------------------------------------------


_SSE_HEARTBEAT_SECONDS = 20.0


@router.get("/stream")
async def stream_alerts(
    request: Request,
    bus: Annotated[AlertBus, Depends(get_alert_bus)],
    stream_id: str | None = Query(
        None, description="filter to a single stream id"
    ),
) -> StreamingResponse:
    """Server-Sent Events feed of rule hits.

    Frame format::

        event: alert
        data: {"stream_id": "...", "rule_name": "...", ...}

    Clients reconnect on disconnect and can backfill missed events via
    ``GET /alerts?stream_id=...`` over the same window.

    A heartbeat comment (``: keepalive``) is sent every
    ``_SSE_HEARTBEAT_SECONDS`` so intermediary proxies don't drop the
    connection during quiet periods.
    """

    async def gen():
        subscription = bus.subscribe()
        # Prime the connection with a comment so browsers flush headers.
        yield ": connected\n\n"
        try:
            while True:
                # Race the next event against the heartbeat + disconnect check.
                next_evt = asyncio.ensure_future(subscription.__anext__())
                done, _pending = await asyncio.wait(
                    {next_evt}, timeout=_SSE_HEARTBEAT_SECONDS
                )
                if await request.is_disconnected():
                    next_evt.cancel()
                    return
                if not done:
                    yield ": keepalive\n\n"
                    next_evt.cancel()
                    continue
                try:
                    ev = next_evt.result()
                except StopAsyncIteration:
                    return
                if stream_id and ev.stream_id != stream_id:
                    continue
                payload = json.dumps(ev.to_dict())
                yield f"event: alert\ndata: {payload}\n\n"
        finally:
            # Ensure the subscription's finally block runs (drops the queue).
            await subscription.aclose()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable nginx buffering if fronted
            "Connection": "keep-alive",
        },
    )
