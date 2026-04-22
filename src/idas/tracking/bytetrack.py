"""ByteTrack: high/low score association, MIT license.

This is a faithful-but-compact port of the ByteTrack association logic
(Zhang et al., 2021, MIT). We keep *everything* in pure Python + our own
:func:`greedy_match` because iDAS frame rates (1–10 fps on CCTV) don't
justify a scipy dependency, and the MIT-only build target forbids pulling
in anything copyleft through the back door.

Differences from the canonical paper implementation:

* Motion model: we use a simple constant-velocity predict step driven by
  the last two bbox centroids. No Kalman filter — fewer moving parts, and
  the IoU-based association tolerates a loose prediction.
* Greedy association in place of Hungarian. At <100 detections per frame
  the assignment is stable and the objective difference is negligible.
* Label carries through from detector (open-vocab): a track's label is
  the most-recent matched detection's label.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count
from typing import ClassVar

from idas.licenses import LicenseTag
from idas.models.schemas import BBox, Detection, Track
from idas.pipeline.tracker import TrackerConfig
from idas.tracking.iou import greedy_match, iou_matrix


@dataclass
class _TrackState:
    """Mutable per-track state, kept outside the public `Track` model."""

    track_id: int
    bbox: BBox
    label: str
    score: float
    hits: int = 1
    age: int = 1
    time_since_update: int = 0
    prev_bbox: BBox | None = None
    history: list[BBox] = field(default_factory=list)

    def predict(self) -> BBox:
        """Constant-velocity prediction from the last two centroids."""
        if self.prev_bbox is None:
            return self.bbox
        dx = self.bbox.cx - self.prev_bbox.cx
        dy = self.bbox.cy - self.prev_bbox.cy
        return BBox(
            x1=max(0.0, min(1.0, self.bbox.x1 + dx)),
            y1=max(0.0, min(1.0, self.bbox.y1 + dy)),
            x2=max(0.0, min(1.0, self.bbox.x2 + dx)),
            y2=max(0.0, min(1.0, self.bbox.y2 + dy)),
        )

    def update(self, det: Detection) -> None:
        self.prev_bbox = self.bbox
        self.bbox = det.bbox
        self.label = det.label
        self.score = det.score
        self.hits += 1
        self.age += 1
        self.time_since_update = 0
        self.history.append(det.bbox)
        if len(self.history) > 50:
            self.history.pop(0)

    def mark_missed(self) -> None:
        self.age += 1
        self.time_since_update += 1


class ByteTracker:
    """ByteTrack, MIT."""

    name: ClassVar[str] = "bytetrack"
    license_tag: ClassVar[LicenseTag] = LicenseTag.MIT

    def __init__(self, config: TrackerConfig | None = None) -> None:
        self.config = config or TrackerConfig()
        self._tracks: list[_TrackState] = []
        self._ids = count(1)

    def reset(self) -> None:
        self._tracks = []
        self._ids = count(1)

    # ---- core association ----------------------------------------------------

    def update(self, detections: list[Detection]) -> list[Track]:
        cfg = self.config

        high = [d for d in detections if d.score >= cfg.high_threshold]
        low = [
            d
            for d in detections
            if cfg.low_threshold <= d.score < cfg.high_threshold
        ]

        # Predict each existing track's position.
        predicted = [t.predict() for t in self._tracks]

        # First pass: high-score detections vs all tracks.
        high_boxes = [d.bbox for d in high]
        mtx = iou_matrix(predicted, high_boxes)
        matches1, unmatched_tracks, unmatched_high = greedy_match(
            mtx, threshold=cfg.match_threshold, n_cols=len(high_boxes)
        )
        for ti, di in matches1:
            self._tracks[ti].update(high[di])

        # Second pass: unmatched tracks vs low-score detections. This is the
        # ByteTrack trick — low-confidence boxes can still "maintain" an
        # existing track even if they wouldn't start a new one.
        low_boxes = [d.bbox for d in low]
        remaining_tracks = [self._tracks[ti] for ti in unmatched_tracks]
        remaining_preds = [predicted[ti] for ti in unmatched_tracks]
        mtx2 = iou_matrix(remaining_preds, low_boxes)
        matches2, still_unmatched, _ = greedy_match(
            mtx2, threshold=cfg.match_threshold * 0.8, n_cols=len(low_boxes)
        )
        matched_low_via_idx = {ti: di for ti, di in matches2}
        for ti_local, di in matches2:
            remaining_tracks[ti_local].update(low[di])

        # Anything still unmatched among tracks ages as "missed".
        for ti_local, t in enumerate(remaining_tracks):
            if ti_local not in matched_low_via_idx:
                t.mark_missed()

        # Evict dead tracks.
        self._tracks = [
            t for t in self._tracks if t.time_since_update <= cfg.track_buffer
        ]

        # Spawn new tracks from unmatched HIGH detections only. Low-score
        # detections never create identities — that's the other half of the
        # ByteTrack trick and what keeps spurious boxes from proliferating.
        for di in unmatched_high:
            det = high[di]
            self._tracks.append(
                _TrackState(
                    track_id=next(self._ids),
                    bbox=det.bbox,
                    label=det.label,
                    score=det.score,
                )
            )

        # Surface only *confirmed* tracks.
        out: list[Track] = []
        for t in self._tracks:
            if t.hits < cfg.min_hits:
                continue
            if t.time_since_update > 0:
                continue  # lost this frame, don't report
            out.append(
                Track(
                    track_id=t.track_id,
                    label=t.label,
                    score=t.score,
                    bbox=t.bbox,
                    age=t.age,
                    hits=t.hits,
                )
            )
        return out
