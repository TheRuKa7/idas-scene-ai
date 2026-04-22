"""AlertBus pub/sub semantics."""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from idas.api.alert_bus import AlertBus, AlertEvent


def _event(stream: str = "s1", rule: str = "r1", opened: bool = True) -> AlertEvent:
    return AlertEvent(
        stream_id=stream,
        rule_name=rule,
        track_id=7,
        label="person",
        score=0.9,
        zone=None,
        ts=datetime.utcnow(),
        opened=opened,
    )


@pytest.mark.asyncio
async def test_publish_delivers_to_single_subscriber() -> None:
    bus = AlertBus()
    received: list[AlertEvent] = []

    async def consume() -> None:
        async for ev in bus.subscribe():
            received.append(ev)
            if len(received) >= 2:
                return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let the subscriber register

    await bus.publish(_event(rule="a"))
    await bus.publish(_event(rule="b"))

    await asyncio.wait_for(task, timeout=1.0)
    assert [e.rule_name for e in received] == ["a", "b"]


@pytest.mark.asyncio
async def test_publish_fans_out_to_multiple_subscribers() -> None:
    bus = AlertBus()
    got_a: list[str] = []
    got_b: list[str] = []

    async def consume(dst: list[str]) -> None:
        async for ev in bus.subscribe():
            dst.append(ev.rule_name)
            return  # take one event and leave

    t1 = asyncio.create_task(consume(got_a))
    t2 = asyncio.create_task(consume(got_b))
    # Both subscribers must register before publish; one event-loop tick
    # per ``subscribe()`` call is enough.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert bus.subscriber_count == 2
    await bus.publish(_event(rule="x"))

    await asyncio.wait_for(asyncio.gather(t1, t2), timeout=1.0)
    assert got_a == ["x"]
    assert got_b == ["x"]


@pytest.mark.asyncio
async def test_slow_subscriber_drops_instead_of_blocking() -> None:
    """The bus is supposed to protect fast publishers from slow subscribers."""
    bus = AlertBus(queue_size=2)
    done = asyncio.Event()

    async def slow_consume() -> None:
        gen = bus.subscribe()
        # Pump the generator once so the subscriber is registered, but never
        # drain further — that means the queue fills up and future publishes
        # have to drop.
        await asyncio.sleep(0)
        await done.wait()
        # Drain to unblock the generator's finally-block on close.
        try:
            async for _ in gen:
                pass
        except Exception:  # noqa: BLE001
            pass

    task = asyncio.create_task(slow_consume())
    await asyncio.sleep(0)

    # Fire more events than the queue holds.
    for i in range(10):
        await bus.publish(_event(rule=f"r{i}"))

    # Some (at least the last few) must have been dropped.
    assert bus.dropped_count > 0
    done.set()
    await bus.close()
    await asyncio.wait_for(task, timeout=1.0)


@pytest.mark.asyncio
async def test_close_terminates_subscribers() -> None:
    bus = AlertBus()
    terminated = asyncio.Event()

    async def consume() -> None:
        async for _ in bus.subscribe():
            pass
        terminated.set()

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await bus.close()
    await asyncio.wait_for(terminated.wait(), timeout=1.0)
    await task
    assert bus.subscriber_count == 0


def test_alert_event_to_dict_isoformat_ts() -> None:
    ev = _event()
    d = ev.to_dict()
    assert isinstance(d["ts"], str)
    # Parseable back as ISO 8601.
    datetime.fromisoformat(d["ts"])
    assert d["stream_id"] == "s1"
    assert d["opened"] is True
