"""Runtime factory — picks detector/tracker based on license mode + config.

This is the one place where the license-mode switch turns into actual
component selection. Everywhere else in the codebase treats components as
interchangeable behind their protocols; here we commit to a choice.

Selection order (standard mode):

    1. If `IDAS_FORCE_STUB=1`, always return StubDetector. Lets CI run the
       full stream pipeline without any weights on disk.
    2. Try YoloWorldSubprocessDetector. It spawns at first `detect()`, so
       construction is cheap; we only pay the process startup on the hot
       path.
    3. On ImportError or weights-not-found-style errors, fall back to
       OWLv2 (Apache-2).
    4. On further failure, fall back to Stub.

Selection order (mit-only mode):

    1. If `IDAS_FORCE_STUB=1`, Stub.
    2. OWLv2 if weights are available.
    3. Stub.

YOLO-World is never attempted in mit-only mode — the constructor's
:func:`assert_allowed` call would raise before the subprocess spawn, and
we trap that as a clear license error rather than silently falling back.
"""
from __future__ import annotations

import logging
import os

from idas.config import settings
from idas.licenses import LicenseTag, LicenseViolation
from idas.models.schemas import LicenseInfo
from idas.perception.stub import StubDetector
from idas.pipeline.detector import BaseDetector, DetectorConfig
from idas.pipeline.tracker import BaseTracker, TrackerConfig
from idas.tracking.bytetrack import ByteTracker

log = logging.getLogger(__name__)


def _force_stub() -> bool:
    return os.environ.get("IDAS_FORCE_STUB", "").strip() in {"1", "true", "yes"}


def build_detector(config: DetectorConfig) -> BaseDetector:
    """Return a detector appropriate for the current license mode."""
    if _force_stub():
        log.info("IDAS_FORCE_STUB set — using StubDetector")
        return StubDetector(config)

    mode = settings.license_mode

    if mode == "standard":
        # Try YOLO-World in a subprocess first (best accuracy).
        try:
            from idas.perception.yolo_world import YoloWorldSubprocessDetector

            return YoloWorldSubprocessDetector(config)
        except LicenseViolation:
            # Shouldn't happen in standard mode, but keep the guard tight.
            log.warning("YOLO-World blocked by license policy; falling back")
        except Exception as exc:  # noqa: BLE001
            log.warning("YOLO-World unavailable (%s); trying OWLv2", exc)

        try:
            from idas.perception.owlv2 import OWLv2Detector

            det = OWLv2Detector(config)
            # Force a weights-check eagerly so we fall back here, not on first frame.
            det._ensure_session()  # noqa: SLF001
            return det
        except Exception as exc:  # noqa: BLE001
            log.warning("OWLv2 unavailable (%s); falling back to Stub", exc)
            return StubDetector(config)

    # mit-only: refuse YOLO-World outright, try OWLv2, else stub.
    assert mode == "mit-only"
    try:
        from idas.perception.owlv2 import OWLv2Detector

        det = OWLv2Detector(config)
        det._ensure_session()  # noqa: SLF001
        return det
    except Exception as exc:  # noqa: BLE001
        log.info("OWLv2 weights unavailable in mit-only mode (%s); using Stub", exc)
        return StubDetector(config)


def build_tracker(config: TrackerConfig | None = None) -> BaseTracker:
    """Tracker choice is not license-sensitive today — ByteTrack is MIT."""
    return ByteTracker(config)


def describe_runtime(detector: BaseDetector, tracker: BaseTracker) -> LicenseInfo:
    """Summarize what's running, for the `/licenses` endpoint."""
    det_tag: LicenseTag = detector.license_tag
    trk_tag: LicenseTag = tracker.license_tag
    return LicenseInfo(
        mode=settings.license_mode,
        detector=detector.name,
        detector_license=det_tag.value,
        tracker=tracker.name,
        tracker_license=trk_tag.value,
        subprocess_isolated=det_tag in {LicenseTag.GPL_3, LicenseTag.AGPL_3},
    )
