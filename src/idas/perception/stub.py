"""Deterministic stub detector.

Used for CI, local dev without weights, and the smoke tests. Given an image
and a prompt set, it returns one fixed-geometry detection per requested
label with a score derived from a hash of (label, image-checksum) so that
snapshot tests remain stable.

This path imports nothing heavier than hashlib — which is critical for the
`mit-only` deployment: it must be possible to run the service with no ML
dependencies installed at all.
"""
from __future__ import annotations

import hashlib
from typing import ClassVar

from idas.licenses import LicenseTag
from idas.models.schemas import BBox, Detection
from idas.pipeline.detector import DetectorConfig


class StubDetector:
    """Deterministic, license-free detector used for CI + fallback."""

    name: ClassVar[str] = "stub"
    license_tag: ClassVar[LicenseTag] = LicenseTag.APACHE_2

    def __init__(self, config: DetectorConfig) -> None:
        self.config = config

    def detect(self, frame_rgb: bytes, width: int, height: int) -> list[Detection]:
        # Hash the frame once so scores are reproducible across runs.
        digest = hashlib.blake2s(frame_rgb, digest_size=8).digest()
        out: list[Detection] = []
        for i, label in enumerate(self.config.prompt_labels):
            # Derive a score in [0.30, 0.99] from the hash + label index.
            byte = digest[i % len(digest)]
            score = 0.30 + (byte / 255.0) * 0.69
            if score < self.config.score_threshold:
                continue
            # Lay out boxes along a diagonal so each label gets a distinct region.
            n = len(self.config.prompt_labels)
            frac = (i + 1) / (n + 1)
            x1 = max(0.0, frac - 0.10)
            y1 = max(0.0, frac - 0.10)
            x2 = min(1.0, frac + 0.10)
            y2 = min(1.0, frac + 0.10)
            out.append(
                Detection(
                    label=label,
                    score=round(score, 4),
                    bbox=BBox(x1=x1, y1=y1, x2=x2, y2=y2),
                )
            )
        return out[: self.config.max_detections]

    def close(self) -> None:  # nothing to release
        return None
