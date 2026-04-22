"""In-process alert pub/sub for SSE fan-out.

A :class:`StreamRunner` publishes a :class:`AlertEvent` every time the rule
evaluator produces an edge transition. HTTP clients subscribe via
``GET /alerts/stream`` and receive events as they happen.

Design choices:

* **Async queue per subscriber** — each ``subscribe()`` call gets its own
  bounded queue; slow subscribers drop events rather than blocking the
  publisher. A stream runner must never stall because a mobile client is
  on a bad network.
* **No persistence** — alerts are persisted separately via the
  ``rule_hits`` table. The bus is purely for live push; consumers that
  miss events can backfill via ``GET /alerts``.
* **In-process only** — this is a single-node topology. For multi-replica
  deployments swap to Redis pub/sub or NATS; the :class:`AlertBus`
  interface is designed to allow that substitution later.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from datetime import datetime

from idas.rules.evaluator import RuleHitEvent

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertEvent:
    """What HTTP subscribers receive. Adds ``stream_id`` + ``hit_id`` to the
    core :class:`RuleHitEvent`."""

    stream_id: str
    rule_name: str
    track_id: int
    label: str
    score: float
    zone: str | None
    ts: datetime
    opened: bool
    hit_id: int | None = None
    clip_path: str | None = None

    @classmethod
    def from_rule_event(
        cls,
        ev: RuleHitEvent,
        *,
        stream_id: str,
        hit_id: int | None = None,
        clip_path: str | None = None,
    ) -> "AlertEvent":
        return cls(
            stream_id=stream_id,
            rule_name=ev.rule_name,
            track_id=ev.track_id,
            label=ev.label,
            score=ev.score,
            zone=ev.zone,
            ts=ev.ts,
            opened=ev.opened,
            hit_id=hit_id,
            clip_path=clip_path,
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        return d


class AlertBus:
    """Fan-out pub/sub. Publishers are synchronous; subscribers are async."""

    def __init__(self, *, queue_size: int = 256) -> None:
        self._subscribers: set[asyncio.Queue[AlertEvent | None]] = set()
        self._queue_size = queue_size
        self._dropped = 0

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def dropped_count(self) -> int:
        """Number of events dropped because a subscriber queue was full.

        Exposed for /metrics later; nonzero values mean a slow consumer.
        """
        return self._dropped

    async def publish(self, ev: AlertEvent) -> None:
        """Deliver `ev` to every live subscriber.

        Queues that are full silently drop the event and bump
        :attr:`dropped_count`. Logging is noisy by default because a
        drop is always a signal — either a misbehaving subscriber or
        a true overload.
        """
        for q in list(self._subscribers):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                self._dropped += 1
                log.warning("alert bus subscriber full; dropped event %s", ev.rule_name)

    def subscribe(self) -> AsyncIterator[AlertEvent]:
        """Return an async iterator over events for a new subscriber.

        The queue is registered **synchronously** so that events published
        between ``subscribe()`` returning and the first ``__anext__`` are
        not lost. The subscription ends when either:

        * the consumer breaks out of the ``async for``, or
        * :meth:`close` is called and pushes a sentinel ``None``.
        """
        q: asyncio.Queue[AlertEvent | None] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(q)
        return self._iter_queue(q)

    async def _iter_queue(
        self, q: asyncio.Queue[AlertEvent | None]
    ) -> AsyncIterator[AlertEvent]:
        try:
            while True:
                ev = await q.get()
                if ev is None:
                    return
                yield ev
        finally:
            self._subscribers.discard(q)

    async def close(self) -> None:
        """Signal every subscriber to terminate.

        Called on app shutdown; idempotent. Must succeed even when a slow
        subscriber's queue is already full — we drop queued events to make
        room for the sentinel, because delivery of the ``None`` is what
        unblocks the consumer's ``async for`` loop.
        """
        subs = list(self._subscribers)
        self._subscribers.clear()
        for q in subs:
            while True:
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    break
            q.put_nowait(None)
