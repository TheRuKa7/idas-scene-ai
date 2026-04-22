"""End-to-end runner registry test.

Exercises the whole hot path — frame source → stub detector → ByteTrack →
rule evaluator → alert bus → DB — without any external dependencies
(ffmpeg, GPU, real weights).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from idas.api.alert_bus import AlertBus, AlertEvent
from idas.api.runner_registry import RunnerRegistry
from idas.models.schemas import StreamCreate
from idas.storage.database import get_session_factory, init_db
from idas.storage.repos import RuleHitRepo, StreamRepo
from idas.streams.source import Frame, StaticFrameSource


def _make_frame() -> Frame:
    # 16x16 black image — the stub detector's scores are deterministic from
    # the hashed bytes, so this is enough to produce predictable detections.
    return Frame(data=b"\x00" * (16 * 16 * 3), width=16, height=16, index=0)


def _fake_source_factory(
    url: str, *, fps: int, width: int, height: int
):
    """Yields 20 copies of a single frame, then terminates."""
    return StaticFrameSource(_make_frame(), limit=20)


@pytest.mark.asyncio
async def test_registry_start_runs_pipeline_and_publishes_alerts(
    tmp_path: Path,
) -> None:
    init_db()
    bus = AlertBus()
    registry = RunnerRegistry(
        bus,
        clip_dir=tmp_path / "clips",
        frame_source_factory=_fake_source_factory,
        fps=10,  # speed up min_hits confirmation
    )

    # Persist a stream spec with a trivial always-match rule.
    spec = StreamCreate(
        name="test-cam",
        url="static://test",
        prompt_labels=["person"],
        rules=[
            {"op": "class_in", "name": "person_seen", "args": {"labels": ["person"]}}
        ],
        zones=[],
    )
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        stream = StreamRepo().create(session, spec, "stream-test")

    # Subscribe BEFORE starting the runner so we don't miss the first open.
    received: list[AlertEvent] = []
    consume_started = asyncio.Event()

    async def consume() -> None:
        consume_started.set()
        async for ev in bus.subscribe():
            received.append(ev)
            if any(e.opened for e in received):
                return

    consumer = asyncio.create_task(consume())
    await consume_started.wait()
    # One more tick so the generator has registered its queue.
    await asyncio.sleep(0)

    await registry.start(stream.id)
    assert registry.is_running(stream.id)

    try:
        await asyncio.wait_for(consumer, timeout=3.0)
    finally:
        await registry.stop(stream.id)

    assert any(ev.opened for ev in received), "runner never published an open event"
    first_open = next(ev for ev in received if ev.opened)
    assert first_open.stream_id == stream.id
    assert first_open.rule_name == "person_seen"
    assert first_open.hit_id is not None

    # DB must have a persisted hit row.
    with SessionLocal() as session:
        hits = RuleHitRepo().list_for_stream(session, stream.id)
    assert len(hits) >= 1
    assert hits[0].rule_name == "person_seen"


@pytest.mark.asyncio
async def test_registry_start_is_idempotent() -> None:
    init_db()
    bus = AlertBus()
    registry = RunnerRegistry(
        bus,
        frame_source_factory=lambda url, **k: StaticFrameSource(_make_frame(), limit=100),
    )

    spec = StreamCreate(
        name="idem", url="static://", prompt_labels=["x"], rules=[], zones=[]
    )
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        stream = StreamRepo().create(session, spec, "stream-idem")

    await registry.start(stream.id)
    await registry.start(stream.id)  # must not raise, must not replace
    assert registry.is_running(stream.id)

    await registry.stop(stream.id)
    await registry.stop(stream.id)  # second stop is a no-op
    assert not registry.is_running(stream.id)


@pytest.mark.asyncio
async def test_registry_start_unknown_stream_raises() -> None:
    init_db()
    registry = RunnerRegistry(
        AlertBus(),
        frame_source_factory=_fake_source_factory,
    )
    with pytest.raises(KeyError):
        await registry.start("does-not-exist")


@pytest.mark.asyncio
async def test_shutdown_all_stops_every_runner() -> None:
    init_db()
    registry = RunnerRegistry(
        AlertBus(),
        frame_source_factory=lambda url, **k: StaticFrameSource(_make_frame(), limit=1000),
    )

    SessionLocal = get_session_factory()
    for sid in ("a", "b", "c"):
        spec = StreamCreate(
            name=sid, url="static://", prompt_labels=["x"], rules=[], zones=[]
        )
        with SessionLocal() as session:
            StreamRepo().create(session, spec, sid)
        await registry.start(sid)

    assert all(registry.is_running(sid) for sid in ("a", "b", "c"))
    await registry.shutdown_all()
    assert not any(registry.is_running(sid) for sid in ("a", "b", "c"))
