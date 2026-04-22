"""Detector interface.

Concrete detectors live under :mod:`idas.perception`. Each one advertises its
license tag so the runtime factory can route correctly. Implementations are
defined as Protocols rather than ABCs because the subprocess-isolated
YOLO-World adapter is structurally compatible but cannot inherit from a class
whose type machinery is loaded in the main process.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from idas.licenses import LicenseTag
from idas.models.schemas import Detection


@dataclass(frozen=True)
class DetectorConfig:
    """Runtime knobs applied uniformly across detectors."""

    prompt_labels: tuple[str, ...]
    score_threshold: float = 0.25
    iou_threshold: float = 0.5
    max_detections: int = 100


@runtime_checkable
class BaseDetector(Protocol):
    """Protocol every detector must satisfy.

    `license_tag` is a class attribute, not a method, so the runtime factory
    can cheaply decide whether a subprocess boundary is required without
    having to instantiate anything.
    """

    name: str
    license_tag: LicenseTag

    def detect(self, frame_rgb: bytes, width: int, height: int) -> list[Detection]:
        """Run detection on a single frame.

        `frame_rgb` is raw RGB bytes of shape (height, width, 3) packed in
        row-major order. Detectors convert to whatever tensor layout they
        need internally. Returning normalized-coord :class:`Detection`s keeps
        downstream tracker/rule code detector-agnostic.
        """
        ...

    def close(self) -> None:
        """Free session handles, subprocess workers, GPU memory, etc."""
        ...
