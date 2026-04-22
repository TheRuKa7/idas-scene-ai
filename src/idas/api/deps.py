"""FastAPI dependencies.

Shared across routes. The singletons below are lazily built so importing
``idas.api.main`` in tests doesn't immediately try to open ffmpeg or spawn
a YOLO-World subprocess.
"""
from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import TYPE_CHECKING

from idas.api.alert_bus import AlertBus
from idas.api.runner_registry import RunnerRegistry
from idas.pipeline.detector import BaseDetector, DetectorConfig
from idas.pipeline.tracker import BaseTracker
from idas.runtime import build_detector, build_tracker
from idas.storage.database import get_session_factory, init_db
from idas.storage.repos import RuleHitRepo, StreamRepo

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# ---- DB session ----------------------------------------------------------------


def get_db_session() -> Iterator["Session"]:
    """FastAPI dep: yield a per-request session."""
    init_db()  # idempotent; creates tables on first call
    SessionLocal = get_session_factory()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ---- repos ---------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_stream_repo() -> StreamRepo:
    return StreamRepo()


@lru_cache(maxsize=1)
def get_hit_repo() -> RuleHitRepo:
    return RuleHitRepo()


# ---- detector / tracker factories ----------------------------------------------
# These build fresh instances per call because each stream owns its own tracker
# state; callers that want to cache do so explicitly.


def make_detector(labels: list[str]) -> BaseDetector:
    return build_detector(
        DetectorConfig(prompt_labels=tuple(labels), score_threshold=0.25)
    )


def make_tracker() -> BaseTracker:
    return build_tracker()


# ---- process-wide singletons ---------------------------------------------------
# These are created the first time a route asks for them, and torn down
# on app shutdown via the lifespan handler in api/main.py.


@lru_cache(maxsize=1)
def get_alert_bus() -> AlertBus:
    return AlertBus()


@lru_cache(maxsize=1)
def get_runner_registry() -> RunnerRegistry:
    return RunnerRegistry(get_alert_bus())


def reset_singletons_for_tests() -> None:
    """Clear bus + registry caches so tests start with fresh state."""
    get_alert_bus.cache_clear()
    get_runner_registry.cache_clear()
