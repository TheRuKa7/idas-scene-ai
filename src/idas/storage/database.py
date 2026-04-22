"""SQLAlchemy engine + session plumbing.

We default to SQLite at `data/idas.db` so `uvicorn idas.api.main:app` works
with zero external services. Production deployments point `IDAS_DB_URL` at
Postgres (e.g. `postgresql+psycopg://user:pwd@host/idas`). The table
definitions stay identical — only the dialect changes.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    DateTime,
    Engine,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from idas.config import settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class Base(DeclarativeBase):
    """SQLAlchemy 2.x declarative base."""


class StreamRow(Base):
    """Persisted stream spec."""

    __tablename__ = "streams"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    url: Mapped[str] = mapped_column(String(1024))
    prompt_labels: Mapped[list] = mapped_column(JSON)
    rules: Mapped[list] = mapped_column(JSON, default=list)
    zones: Mapped[list] = mapped_column(JSON, default=list)
    state: Mapped[str] = mapped_column(String(32), default="idle")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_frame_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    hits: Mapped[list["RuleHitRow"]] = relationship(
        back_populates="stream", cascade="all,delete-orphan"
    )


class RuleHitRow(Base):
    """Persisted rule hit. One row per (rule, track) open+close cycle."""

    __tablename__ = "rule_hits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stream_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("streams.id", ondelete="CASCADE")
    )
    rule_name: Mapped[str] = mapped_column(String(128))
    track_id: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(128))
    t_start: Mapped[datetime] = mapped_column(DateTime)
    t_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    score: Mapped[float] = mapped_column(Float)
    zone: Mapped[str | None] = mapped_column(String(128), nullable=True)
    clip_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    stream: Mapped[StreamRow] = relationship(back_populates="hits")


# ---- engine + session factory ---------------------------------------------------

SessionFactory = sessionmaker  # type alias for readability


_engine: Engine | None = None
_session_factory: sessionmaker["Session"] | None = None


def _db_url() -> str:
    """Respect IDAS_DB_URL, else SQLite under settings.data_dir."""
    url = os.environ.get("IDAS_DB_URL")
    if url:
        return url
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(settings.data_dir / 'idas.db').as_posix()}"


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = _db_url()
        # SQLite + threaded FastAPI requires check_same_thread=False.
        kwargs: dict = {"future": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kwargs)
    return _engine


def get_session_factory() -> sessionmaker["Session"]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False, future=True
        )
    return _session_factory


def init_db() -> None:
    """Create tables if they don't exist. Idempotent."""
    Base.metadata.create_all(get_engine())


def reset_engine_for_tests() -> None:
    """Drop cached engine — tests use this to swap to an in-memory DB."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
