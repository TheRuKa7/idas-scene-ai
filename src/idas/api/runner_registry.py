"""Global registry of active :class:`StreamRunner` instances.

Lives for the lifetime of the FastAPI app. One registry → one event loop,
which is what FastAPI already guarantees. Multi-worker deployments need a
shared registry (Redis, a dedicated scheduler) — out of scope here.

The registry owns:

* A map ``stream_id → StreamRunner``.
* A reference to the shared :class:`AlertBus` so it can hand each runner
  the right publish callback.
* The filesystem root for clip output.

Public surface: :meth:`start`, :meth:`stop`, :meth:`shutdown_all`,
:meth:`is_running`.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from idas.api.alert_bus import AlertBus
from idas.config import settings
from idas.models.schemas import RuleDef, Zone
from idas.pipeline.detector import DetectorConfig
from idas.pipeline.runner import StreamRunner
from idas.rules.evaluator import RuleEvaluator
from idas.runtime import build_detector, build_tracker
from idas.storage.database import get_session_factory
from idas.storage.repos import StreamRepo
from idas.streams.source import FFmpegFrameSource, FrameSource

log = logging.getLogger(__name__)


# Test / dev hook: supply a custom :class:`FrameSource` factory so unit
# tests don't need an ffmpeg binary. Signature matches FFmpegFrameSource.
FrameSourceFactory = callable  # (url: str, *, fps: int, width: int, height: int) -> FrameSource


class RunnerRegistry:
    """Process-wide registry of live stream runners."""

    def __init__(
        self,
        bus: AlertBus,
        *,
        clip_dir: Path | None = None,
        frame_source_factory: FrameSourceFactory | None = None,
        fps: int = 5,
        frame_width: int = 640,
        frame_height: int = 360,
    ) -> None:
        self._bus = bus
        self._clip_dir = clip_dir or (settings.data_dir / "clips")
        self._fps = fps
        self._width = frame_width
        self._height = frame_height
        self._runners: dict[str, StreamRunner] = {}
        self._lock = asyncio.Lock()
        self._factory: FrameSourceFactory = (
            frame_source_factory or self._default_factory
        )

    # ---- public API ----------------------------------------------------------

    def is_running(self, stream_id: str) -> bool:
        runner = self._runners.get(stream_id)
        return runner is not None and runner.is_running

    async def start(self, stream_id: str) -> None:
        """Start the runner for an existing stream spec.

        Raises :class:`KeyError` if the stream spec doesn't exist.
        Idempotent: calling ``start`` on a running stream is a no-op.
        """
        async with self._lock:
            if self.is_running(stream_id):
                return

            SessionLocal = get_session_factory()
            with SessionLocal() as session:
                stream = StreamRepo().get(session, stream_id)
            if stream is None:
                raise KeyError(stream_id)

            # Build the frame source first — it's the cheapest thing to tear
            # down if construction of anything downstream fails.
            source: FrameSource = self._factory(
                stream.url, fps=self._fps, width=self._width, height=self._height
            )

            detector = build_detector(
                DetectorConfig(prompt_labels=tuple(stream.prompt_labels))
            )
            tracker = build_tracker()

            rules = [RuleDef.model_validate(r) for r in stream.rules]
            zones = [Zone.model_validate(z) for z in stream.zones]
            evaluator = RuleEvaluator(rules, zones)

            async def _publish(payload: dict) -> None:
                from idas.api.alert_bus import AlertEvent  # local to avoid cycle
                from datetime import datetime

                ts = payload["ts"]
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts)
                await self._bus.publish(
                    AlertEvent(
                        stream_id=payload["stream_id"],
                        rule_name=payload["rule_name"],
                        track_id=payload["track_id"],
                        label=payload["label"],
                        score=payload["score"],
                        zone=payload["zone"],
                        ts=ts,
                        opened=payload["opened"],
                        hit_id=payload.get("hit_id"),
                        clip_path=payload.get("clip_path"),
                    )
                )

            runner = StreamRunner(
                stream=stream,
                source=source,
                detector=detector,
                tracker=tracker,
                evaluator=evaluator,
                on_event=_publish,
                clip_dir=self._clip_dir,
                fps=self._fps,
            )
            runner.start()
            self._runners[stream_id] = runner
            log.info("started runner for stream=%s", stream_id)

    async def stop(self, stream_id: str) -> bool:
        """Stop and remove a runner. Returns True if something was stopped."""
        async with self._lock:
            runner = self._runners.pop(stream_id, None)
        if runner is None:
            return False
        await runner.stop()
        log.info("stopped runner for stream=%s", stream_id)
        return True

    async def shutdown_all(self) -> None:
        """Stop every running stream. Called during app shutdown."""
        async with self._lock:
            runners = list(self._runners.items())
            self._runners.clear()
        for stream_id, runner in runners:
            try:
                await runner.stop()
            except Exception:  # noqa: BLE001
                log.exception("error stopping runner %s", stream_id)

    # ---- defaults ------------------------------------------------------------

    @staticmethod
    def _default_factory(
        url: str, *, fps: int, width: int, height: int
    ) -> FrameSource:
        return FFmpegFrameSource(url, fps=fps, width=width, height=height)
