"""Tracker interface."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from idas.licenses import LicenseTag
from idas.models.schemas import Detection, Track


@dataclass(frozen=True)
class TrackerConfig:
    """ByteTrack-compatible knobs; other trackers may ignore some."""

    high_threshold: float = 0.5
    low_threshold: float = 0.1
    match_threshold: float = 0.7  # IoU for associating tracks to detections
    track_buffer: int = 30  # frames a lost track is kept alive
    min_hits: int = 3  # confirmation hits before a track is reported


@runtime_checkable
class BaseTracker(Protocol):
    """Minimal tracker protocol: update with detections, get active tracks back."""

    name: str
    license_tag: LicenseTag

    def update(self, detections: list[Detection]) -> list[Track]:
        """Advance by one frame.

        Returns only *confirmed* tracks (hits >= `min_hits`). Probationary
        tracks are kept internally but not surfaced — that keeps the
        downstream rule engine from firing on flicker.
        """
        ...

    def reset(self) -> None:
        """Drop all track state. Used when a stream restarts."""
        ...
