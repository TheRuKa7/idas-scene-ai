"""Repository layer — thin wrappers over SQLAlchemy sessions.

Repos keep SQL knowledge out of the API routes. Every method accepts an
explicit :class:`Session` so request-scoped transactions stay composable.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from idas.models.schemas import RuleHit, Stream, StreamCreate
from idas.storage.database import RuleHitRow, StreamRow

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class StreamRepo:
    """CRUD for stream specs."""

    def create(self, session: "Session", spec: StreamCreate, stream_id: str) -> Stream:
        row = StreamRow(
            id=stream_id,
            name=spec.name,
            url=spec.url,
            prompt_labels=list(spec.prompt_labels),
            rules=[r.model_dump() for r in spec.rules],
            zones=[z.model_dump() for z in spec.zones],
            state="idle",
            created_at=datetime.utcnow(),
        )
        session.add(row)
        session.commit()
        return _row_to_stream(row)

    def get(self, session: "Session", stream_id: str) -> Stream | None:
        row = session.get(StreamRow, stream_id)
        return _row_to_stream(row) if row else None

    def list(self, session: "Session") -> list[Stream]:
        rows = session.scalars(select(StreamRow).order_by(StreamRow.created_at)).all()
        return [_row_to_stream(r) for r in rows]

    def set_state(
        self,
        session: "Session",
        stream_id: str,
        *,
        state: str,
        error: str | None = None,
    ) -> None:
        row = session.get(StreamRow, stream_id)
        if row is None:
            return
        row.state = state
        row.error = error
        session.commit()

    def touch(self, session: "Session", stream_id: str, ts: datetime) -> None:
        row = session.get(StreamRow, stream_id)
        if row is None:
            return
        row.last_frame_at = ts
        session.commit()

    def delete(self, session: "Session", stream_id: str) -> bool:
        row = session.get(StreamRow, stream_id)
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


class RuleHitRepo:
    """Append + query for rule hits."""

    def open(
        self,
        session: "Session",
        *,
        stream_id: str,
        rule_name: str,
        track_id: int,
        label: str,
        score: float,
        zone: str | None,
        t_start: datetime,
    ) -> int:
        row = RuleHitRow(
            stream_id=stream_id,
            rule_name=rule_name,
            track_id=track_id,
            label=label,
            score=score,
            zone=zone,
            t_start=t_start,
        )
        session.add(row)
        session.commit()
        return row.id

    def close(
        self,
        session: "Session",
        *,
        stream_id: str,
        rule_name: str,
        track_id: int,
        t_end: datetime,
        clip_path: str | None = None,
    ) -> bool:
        stmt = (
            select(RuleHitRow)
            .where(
                RuleHitRow.stream_id == stream_id,
                RuleHitRow.rule_name == rule_name,
                RuleHitRow.track_id == track_id,
                RuleHitRow.t_end.is_(None),
            )
            .order_by(RuleHitRow.id.desc())
            .limit(1)
        )
        row = session.scalars(stmt).first()
        if row is None:
            return False
        row.t_end = t_end
        if clip_path:
            row.clip_path = clip_path
        session.commit()
        return True

    def list_for_stream(
        self,
        session: "Session",
        stream_id: str,
        *,
        limit: int = 100,
    ) -> list[RuleHit]:
        stmt = (
            select(RuleHitRow)
            .where(RuleHitRow.stream_id == stream_id)
            .order_by(RuleHitRow.t_start.desc())
            .limit(limit)
        )
        rows = session.scalars(stmt).all()
        return [_row_to_hit(r) for r in rows]

    def list_recent(self, session: "Session", *, limit: int = 100) -> list[RuleHit]:
        stmt = select(RuleHitRow).order_by(RuleHitRow.t_start.desc()).limit(limit)
        rows = session.scalars(stmt).all()
        return [_row_to_hit(r) for r in rows]


# ---- row → DTO converters ------------------------------------------------------


def _row_to_stream(row: StreamRow) -> Stream:
    return Stream(
        id=row.id,
        name=row.name,
        url=row.url,
        prompt_labels=list(row.prompt_labels or []),
        rules=list(row.rules or []),
        zones=list(row.zones or []),
        state=row.state,  # type: ignore[arg-type]
        created_at=row.created_at,
        last_frame_at=row.last_frame_at,
        error=row.error,
    )


def _row_to_hit(row: RuleHitRow) -> RuleHit:
    return RuleHit(
        id=row.id,
        stream_id=row.stream_id,
        rule_name=row.rule_name,
        track_id=row.track_id,
        label=row.label,
        t_start=row.t_start,
        t_end=row.t_end,
        score=row.score,
        zone=row.zone,
        clip_path=row.clip_path,
    )
