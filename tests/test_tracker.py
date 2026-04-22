"""ByteTracker: identity continuity + new-track spawning."""
from __future__ import annotations

from idas.models.schemas import BBox, Detection
from idas.pipeline.tracker import TrackerConfig
from idas.tracking.bytetrack import ByteTracker
from idas.tracking.iou import iou


def _det(label: str, x1: float, y1: float, x2: float, y2: float, s: float = 0.9) -> Detection:
    return Detection(label=label, score=s, bbox=BBox(x1=x1, y1=y1, x2=x2, y2=y2))


def test_iou_identity() -> None:
    b = BBox(x1=0.1, y1=0.1, x2=0.3, y2=0.3)
    assert iou(b, b) == 1.0


def test_iou_no_overlap() -> None:
    a = BBox(x1=0.0, y1=0.0, x2=0.1, y2=0.1)
    b = BBox(x1=0.5, y1=0.5, x2=0.6, y2=0.6)
    assert iou(a, b) == 0.0


def test_tracker_confirms_after_min_hits() -> None:
    tr = ByteTracker(TrackerConfig(min_hits=3, match_threshold=0.3))
    d = _det("person", 0.1, 0.1, 0.2, 0.2)
    # frame 1, 2 — below min_hits threshold, should return no confirmed tracks
    assert tr.update([d]) == []
    assert tr.update([d]) == []
    # frame 3 — now confirmed
    out = tr.update([d])
    assert len(out) == 1
    assert out[0].label == "person"
    assert out[0].track_id == 1


def test_tracker_maintains_identity_across_motion() -> None:
    tr = ByteTracker(TrackerConfig(min_hits=2, match_threshold=0.3))
    # Two close frames, then a slight motion — IoU still > threshold.
    tr.update([_det("car", 0.1, 0.1, 0.3, 0.3)])
    out1 = tr.update([_det("car", 0.11, 0.11, 0.31, 0.31)])
    assert len(out1) == 1
    id1 = out1[0].track_id
    out2 = tr.update([_det("car", 0.12, 0.12, 0.32, 0.32)])
    assert len(out2) == 1
    assert out2[0].track_id == id1, "identity should persist under small motion"


def test_tracker_spawns_separate_ids_for_distant_detections() -> None:
    tr = ByteTracker(TrackerConfig(min_hits=1, match_threshold=0.3))
    out = tr.update(
        [
            _det("person", 0.0, 0.0, 0.1, 0.1),
            _det("person", 0.8, 0.8, 0.9, 0.9),
        ]
    )
    assert len({t.track_id for t in out}) == 2


def test_low_score_does_not_spawn_but_does_maintain() -> None:
    tr = ByteTracker(TrackerConfig(min_hits=1, match_threshold=0.3,
                                   high_threshold=0.5, low_threshold=0.1))
    # High-score detection spawns a track.
    out = tr.update([_det("p", 0.1, 0.1, 0.2, 0.2, s=0.9)])
    assert len(out) == 1
    # Low-score detection at the same spot should maintain (not reset).
    out2 = tr.update([_det("p", 0.11, 0.11, 0.21, 0.21, s=0.2)])
    assert len(out2) == 1
    assert out2[0].track_id == out[0].track_id
    # A lone low-score detection in an empty tracker should NOT create a track.
    tr.reset()
    assert tr.update([_det("p", 0.1, 0.1, 0.2, 0.2, s=0.2)]) == []
