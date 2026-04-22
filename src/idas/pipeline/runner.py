"""Stream runner: frame source → detector → tracker → rule evaluator.

One :class:`StreamRunner` instance per live stream. The runner owns its
detector/tracker instances, which keeps subprocess lifetimes tied 1:1 to
stream lifetimes. Cancelling the run task terminates the ffmpeg child and
the YOLO-World worker in the same shutdown sequence.

Per-frame it does:

1. Pull a frame from the :class:`FrameSource`.
2. Push it into the pre-event ring buffer (for clip extraction).
3. Feed the frame into any active :class:`ClipWriter` instances collecting
   post-event footage.
4. Run detect → track → evaluate rules.
5. Persist rule edges via :class:`RuleHitRepo`, emit :class:`AlertEvent`s
   on the bus, and spawn / retire :class:`ClipWriter`s.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from idas.models.schemas import Stream
from idas.pipeline.clip_writer import ClipWriter
from idas.pipeline.detector import BaseDetector, DetectorConfig
from idas.pipeline.tracker import BaseTracker
from idas.rules.evaluator import RuleEvaluator
from idas.storage.database import get_session_factory
from idas.storage.repos import RuleHitRepo, StreamRepo
from idas.streams.source import Frame, FrameSource

log = logging.getLogger(__name__)


# An `on_event` callback takes a runner-scoped alert payload (already
# enriched with stream_id + hit_id) and returns an awaitable. We type
# it as a dict to keep this module free of API-layer imports.
EventCallback = Callable[[dict], Awaitable[None]]


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
        on_event: EventCallback | None = None,
        clip_dir: Path | None = None,
        clip_pre_seconds: float = 3.0,
        clip_post_seconds: float = 5.0,
        fps: int = 5,
    ) -> None:
        self.stream = stream
        self.source = source
        self.detector = detector
        self.tracker = tracker
        self.evaluator = evaluator
        self.stream_repo = stream_repo or StreamRepo()
        self.hit_repo = hit_repo or RuleHitRepo()
        self._on_event = on_event
        self._clip_dir = clip_dir
        self._fps = max(1, fps)

        # Ring buffer of the most recent N frames for pre-event clip footage.
        self._pre_cap = max(1, int(clip_pre_seconds * self._fps))
        self._post_cap = max(1, int(clip_post_seconds * self._fps))
        self._ring: deque[Frame] = deque(maxlen=self._pre_cap)

        # Active writers, keyed by (rule_name, track_id). One per open hit.
        self._writers: dict[tuple[str, int], tuple[ClipWriter, int]] = {}

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
            await self._abort_writers()
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

                # 1. ring buffer + feed any active clip writers
                self._ring.append(frame)
                await self._feed_writers(frame)

                # 2. detect → track → evaluate
                detections = self.detector.detect(
                    frame.data, frame.width, frame.height
                )
                tracks = self.tracker.update(detections)
                events = self.evaluator.evaluate(tracks, ts)

                # 3. persist + publish
                if events:
                    await self._handle_events(events, ts)

                # Touch DB less frequently than every frame to keep write load sane.
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
        finally:
            # Gracefully finalize whatever clips remain in flight; the stream
            # loop is over, so every writer should flush what it has.
            await self._flush_writers()

    # ---- event handling ------------------------------------------------------

    async def _handle_events(
        self, events: list, ts: datetime
    ) -> None:
        SessionLocal = get_session_factory()
        for ev in events:
            key = (ev.rule_name, ev.track_id)
            hit_id: int | None = None

            with SessionLocal() as session:
                if ev.opened:
                    hit_id = self.hit_repo.open(
                        session,
                        stream_id=self.stream.id,
                        rule_name=ev.rule_name,
                        track_id=ev.track_id,
                        label=ev.label,
                        score=ev.score,
                        zone=ev.zone,
                        t_start=ev.ts,
                    )
                    await self._spawn_writer(key, hit_id)
                else:
                    self.hit_repo.close(
                        session,
                        stream_id=self.stream.id,
                        rule_name=ev.rule_name,
                        track_id=ev.track_id,
                        t_end=ev.ts,
                    )
                    # Fire-and-forget: finalize clip in background so it can't
                    # stall the hot loop on a slow ffmpeg encode.
                    asyncio.create_task(self._retire_writer(key))

            if self._on_event is not None:
                payload = {
                    "stream_id": self.stream.id,
                    "rule_name": ev.rule_name,
                    "track_id": ev.track_id,
                    "label": ev.label,
                    "score": ev.score,
                    "zone": ev.zone,
                    "ts": ev.ts.isoformat(),
                    "opened": ev.opened,
                    "hit_id": hit_id,
                    "clip_path": None,  # filled in on close-finalize
                }
                try:
                    await self._on_event(payload)
                except Exception:  # noqa: BLE001
                    log.exception("alert bus publish failed")

    # ---- clip writer lifecycle -----------------------------------------------

    async def _spawn_writer(self, key: tuple[str, int], hit_id: int) -> None:
        if self._clip_dir is None:
            return
        if key in self._writers:
            return  # defensive — evaluator should have closed the prior one
        writer = ClipWriter(
            stream_id=self.stream.id,
            hit_id=hit_id,
            pre_frames=list(self._ring),
            post_target=self._post_cap,
            fps=self._fps,
            clip_dir=self._clip_dir,
        )
        await writer.start()
        self._writers[key] = (writer, hit_id)

    async def _feed_writers(self, frame: Frame) -> None:
        if not self._writers:
            return
        # Iterate over a snapshot — ingestion may trigger completion which
        # we handle on the next tick via _retire_writer.
        for key, (writer, _hit_id) in list(self._writers.items()):
            await writer.ingest(frame)
            if writer.is_complete:
                asyncio.create_task(self._retire_writer(key))

    async def _retire_writer(self, key: tuple[str, int]) -> None:
        pair = self._writers.pop(key, None)
        if pair is None:
            return
        writer, hit_id = pair
        clip_path = await writer.finalize()
        if not clip_path:
            return
        SessionLocal = get_session_factory()
        with SessionLocal() as session:
            # The hit may be still open (clip finished first) or already closed
            # (evaluator closed it first). Write the clip path in either case
            # by looking up the row by id directly.
            from idas.storage.database import RuleHitRow  # local import

            row = session.get(RuleHitRow, hit_id)
            if row is not None:
                row.clip_path = clip_path
                session.commit()
        # Emit a follow-up event so subscribers can update UI with the path.
        if self._on_event is not None:
            try:
                await self._on_event(
                    {
                        "stream_id": self.stream.id,
                        "rule_name": key[0],
                        "track_id": key[1],
                        "label": "",
                        "score": 0.0,
                        "zone": None,
                        "ts": datetime.utcnow().isoformat(),
                        "opened": False,
                        "hit_id": hit_id,
                        "clip_path": clip_path,
                    }
                )
            except Exception:  # noqa: BLE001
                log.exception("alert bus clip-ready publish failed")

    async def _flush_writers(self) -> None:
        """At stream end, finalize whatever each writer has captured."""
        keys = list(self._writers)
        await asyncio.gather(
            *(self._retire_writer(k) for k in keys), return_exceptions=True
        )

    async def _abort_writers(self) -> None:
        """At explicit stop, discard in-flight clips without encoding."""
        for writer, _hit_id in list(self._writers.values()):
            await writer.abort()
        self._writers.clear()


# ---- helpers -------------------------------------------------------------------


def default_detector_config(stream: Stream) -> DetectorConfig:
    return DetectorConfig(
        prompt_labels=tuple(stream.prompt_labels),
        score_threshold=0.25,
        iou_threshold=0.5,
        max_detections=100,
    )
