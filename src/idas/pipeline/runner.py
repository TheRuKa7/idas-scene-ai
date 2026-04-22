"""Stream runner: frame source → detector → tracker → rule evaluator.

One :class:`StreamRunner` instance per live stream. The runner owns its
detector/tracker instances, which keeps subprocess lifetimes tied 1:1 to
stream lifetimes. Cancelling the run task terminates the ffmpeg child and
the YOLO-World worker in the same shutdown sequence.

The runner is intentionally small. It does three things:

1. Pump frames from the :class:`FrameSource`.
2. Run detect → track → evaluate rules.
3. Persist rule edges via :class:`RuleHitRepo` and update stream state.

Anything richer (clip extraction, webhook fan-out) lives in post-commit
hooks so the hot path stays synchronous-looking.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from idas.models.schemas import Stream
from idas.pipeline.detector import BaseDetector, DetectorConfig
from idas.pipeline.tracker import BaseTracker
from idas.rules.evaluator import RuleEvaluator
from idas.storage.database import get_session_factory
from idas.storage.repos import RuleHitRepo, StreamRepo
from idas.streams.source import FrameSource

log = logging.getLogger(__name__)


class StreamRunner:
    """Owns a frame loop + detector + tracker + evaluator for one stream."""

    def __init__(
        self,
        *,
        stream: Stream,
        source: FrameSource,
        detector: BaseDetector,
        tracker: BaseTracker,
        evaluator: RuleEvaluator,
        stream_repo: StreamRepo | None = None,
        hit_repo: RuleHitRepo | None = None,
    ) -> None:
        self.stream = stream
        self.source = source
        self.detector = detector
        self.tracker = tracker
        self.evaluator = evaluator
        self.stream_repo = stream_repo or StreamRepo()
        self.hit_repo = hit_repo or RuleHitRepo()
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.is_running:
            return
        self._task = asyncio.create_task(self._run(), name=f"stream:{self.stream.id}")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        finally:
            self._task = None
            await self.source.close()
            self.detector.close()

    # ---- the hot loop --------------------------------------------------------

    async def _run(self) -> None:
        SessionLocal = get_session_factory()
        with SessionLocal() as session:
            self.stream_repo.set_state(session, self.stream.id, state="running")

        try:
            async for frame in self.source:
                ts = datetime.utcnow()
                detections = self.detector.detect(
                    frame.data, frame.width, frame.height
                )
                tracks = self.tracker.update(detections)
                events = self.evaluator.evaluate(tracks, ts)

                if events:
                    with SessionLocal() as session:
                        for ev in events:
                            if ev.opened:
                                self.hit_repo.open(
                                    session,
                                    stream_id=self.stream.id,
                                    rule_name=ev.rule_name,
                                    track_id=ev.track_id,
                                    label=ev.label,
                                    score=ev.score,
                                    zone=ev.zone,
                                    t_start=ev.ts,
                                )
                            else:
                                self.hit_repo.close(
                                    session,
                                    stream_id=self.stream.id,
                                    rule_name=ev.rule_name,
                                    track_id=ev.track_id,
                                    t_end=ev.ts,
                                )

                # Touch less frequently than every frame to keep write load sane.
                if frame.index % 30 == 0:
                    with SessionLocal() as session:
                        self.stream_repo.touch(session, self.stream.id, ts)

        except asyncio.CancelledError:
            with SessionLocal() as session:
                self.stream_repo.set_state(session, self.stream.id, state="stopped")
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("stream runner crashed")
            with SessionLocal() as session:
                self.stream_repo.set_state(
                    session, self.stream.id, state="errored", error=str(exc)
                )


# ---- helpers -------------------------------------------------------------------


def default_detector_config(stream: Stream) -> DetectorConfig:
    return DetectorConfig(
        prompt_labels=tuple(stream.prompt_labels),
        score_threshold=0.25,
        iou_threshold=0.5,
        max_detections=100,
    )
