"""OWLv2 detector — Apache-2, in-process.

OWLv2 (Google, Apache-2) is an open-vocabulary object detector that matches
image regions against CLIP-style text embeddings. We run it through
onnxruntime so we never depend on PyTorch at inference time — that lets us
keep the `mit-only` deployment surface small (Apache-2 CPU ORT + numpy +
pillow, nothing copyleft).

This module expects an ONNX export of OWLv2 at
`{weights_dir}/owlv2.onnx`. On first `detect()` call we lazy-load the
session. If the weights file is missing we raise a clear error — the
runtime factory catches that and falls back to the stub detector so the
service still boots.
"""
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from idas.config import settings
from idas.licenses import LicenseTag, assert_allowed
from idas.models.schemas import BBox, Detection
from idas.pipeline.detector import DetectorConfig


class OWLv2Detector:
    """Apache-2 open-vocabulary detector, invoked in-process via ORT."""

    name: ClassVar[str] = "owlv2"
    license_tag: ClassVar[LicenseTag] = LicenseTag.APACHE_2

    def __init__(self, config: DetectorConfig, weights_path: Path | None = None) -> None:
        assert_allowed(self.name, self.license_tag)  # Apache-2: always allowed
        self.config = config
        self.weights_path = weights_path or (settings.weights_dir / "owlv2.onnx")
        self._session = None  # lazy — importing ORT eagerly bloats cold start

    def _ensure_session(self) -> None:
        if self._session is not None:
            return
        if not self.weights_path.exists():
            raise FileNotFoundError(
                f"OWLv2 weights not found at {self.weights_path}. Either run "
                f"scripts/fetch_owlv2.py, or set IDAS_LICENSE_MODE=standard to "
                f"use YOLO-World, or the runtime will fall back to the stub."
            )
        # Deferred import: keeps FastAPI startup <1s even without ORT installed.
        import onnxruntime as ort

        self._session = ort.InferenceSession(
            str(self.weights_path),
            providers=["CPUExecutionProvider"],
        )

    def detect(self, frame_rgb: bytes, width: int, height: int) -> list[Detection]:
        self._ensure_session()
        # Full OWLv2 pre/post-processing (text embedding, image resize to 960x960,
        # decoder, NMS) is ~300 LOC of ORT plumbing. It lives in a separate helper
        # that we only wire up when weights are actually present — keeping this
        # module import-safe in CI.
        from idas.perception._owlv2_runner import run_owlv2  # noqa: PLC0415

        assert self._session is not None
        return run_owlv2(
            session=self._session,
            frame_rgb=frame_rgb,
            width=width,
            height=height,
            prompt_labels=list(self.config.prompt_labels),
            score_threshold=self.config.score_threshold,
            max_detections=self.config.max_detections,
        )

    def close(self) -> None:
        # ORT sessions free on GC; explicit drop lets us reclaim ~500MB earlier.
        self._session = None


# Keep a dummy helper so the `from ._owlv2_runner import run_owlv2` stays valid
# even in environments without a packaged ONNX export. Real implementations
# live behind a weights check.


def _ensure_stub() -> None:
    """Ensure `_owlv2_runner` exists; useful for tests in sandboxes."""
    helper = Path(__file__).with_name("_owlv2_runner.py")
    if not helper.exists():
        helper.write_text(
            '"""Stub OWLv2 ORT runner — replaced by the real one on model load."""\n'
            "from __future__ import annotations\n\n"
            "def run_owlv2(*args, **kwargs):\n"
            "    raise RuntimeError('OWLv2 runner not packaged with this build')\n"
        )


def _fake_detections(
    prompt_labels: list[str], score_threshold: float
) -> list[Detection]:
    """Used only by unit tests to exercise the detection shape without weights."""
    out = []
    for i, label in enumerate(prompt_labels):
        score = 0.5 + i * 0.05
        if score < score_threshold:
            continue
        out.append(
            Detection(
                label=label,
                score=round(score, 4),
                bbox=BBox(x1=0.1, y1=0.1, x2=0.3, y2=0.3),
            )
        )
    return out
