"""Deterministic stub detector sanity checks."""
from __future__ import annotations

from idas.perception.stub import StubDetector
from idas.pipeline.detector import DetectorConfig


def test_stub_is_deterministic() -> None:
    cfg = DetectorConfig(prompt_labels=("person", "car"), score_threshold=0.0)
    d = StubDetector(cfg)
    frame = b"\x00" * (64 * 64 * 3)
    out1 = d.detect(frame, 64, 64)
    out2 = d.detect(frame, 64, 64)
    assert out1 == out2


def test_stub_respects_threshold() -> None:
    cfg = DetectorConfig(prompt_labels=("a", "b", "c"), score_threshold=0.99)
    d = StubDetector(cfg)
    out = d.detect(b"\x00" * 12, 2, 2)
    # With threshold 0.99 few (possibly zero) stub scores pass.
    assert all(x.score >= 0.99 for x in out)


def test_stub_one_detection_per_label_at_low_threshold() -> None:
    cfg = DetectorConfig(prompt_labels=("a", "b", "c"), score_threshold=0.0)
    d = StubDetector(cfg)
    out = d.detect(b"\xff" * (16 * 16 * 3), 16, 16)
    labels = {x.label for x in out}
    assert labels == {"a", "b", "c"}
