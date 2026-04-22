"""YOLO-World subprocess adapter.

YOLO-World is the strongest open-vocab detector we support, but the most
accessible packaging of it (Ultralytics) is AGPL / GPL-3. To keep the iDAS
core Apache-2 in spirit and in symbol, we never import it: instead we spawn
:mod:`idas.perception._yolo_world_worker` as a child process and exchange
detections as length-prefixed JSON over stdio.

Consequences:

* The parent Python process loads no GPL-3 symbols.
* The child is a disposable process; killing iDAS kills the detector.
* The child is only reachable via a well-typed, schema-validated boundary
  (:class:`WorkerRequest` / :class:`WorkerResponse`).
* In `mit-only` license mode, instantiating this class raises before the
  subprocess is spawned.

The worker script imports Ultralytics. That script is Apache-2 itself (this
file) but the Ultralytics dependency it pulls is AGPL-3 — which is why we
do not import that script from the parent process.
"""
from __future__ import annotations

import base64
import json
import struct
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel

from idas.licenses import LicenseTag, assert_allowed
from idas.models.schemas import Detection
from idas.pipeline.detector import DetectorConfig


class WorkerRequest(BaseModel):
    """Stdin frame → child."""

    kind: str = "detect"
    image_b64: str
    width: int
    height: int
    prompt_labels: list[str]
    score_threshold: float
    max_detections: int


class WorkerResponse(BaseModel):
    """Stdout frame ← child."""

    kind: str  # "ok" | "error"
    detections: list[Detection] = []
    error: str | None = None


class YoloWorldSubprocessDetector:
    """Subprocess-isolated YOLO-World detector.

    `license_tag` reports GPL-3 to the runtime; :func:`assert_allowed` uses
    it to refuse instantiation under `mit-only`. In `standard` mode the
    subprocess boundary is what keeps the core import graph Apache-2.
    """

    name: ClassVar[str] = "yolo-world-subprocess"
    license_tag: ClassVar[LicenseTag] = LicenseTag.GPL_3

    def __init__(self, config: DetectorConfig, worker_path: Path | None = None) -> None:
        # This call is the gate: in `mit-only` it raises LicenseViolation
        # before we ever try to spawn the child.
        assert_allowed(self.name, self.license_tag)

        self.config = config
        self.worker_path = worker_path or (
            Path(__file__).with_name("_yolo_world_worker.py")
        )
        self._proc: subprocess.Popen[bytes] | None = None

    # ---- subprocess lifecycle -------------------------------------------------

    def _ensure_proc(self) -> subprocess.Popen[bytes]:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        # Spawn with the bundled worker script. `-u` = unbuffered stdio so
        # length-prefixed framing is not held up in a Python buffer.
        self._proc = subprocess.Popen(
            [sys.executable, "-u", str(self.worker_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        return self._proc

    # ---- length-prefixed framing ---------------------------------------------
    # A 4-byte big-endian length, then UTF-8 JSON. Lets us send arbitrarily
    # large base64 images without worrying about newline terminators inside
    # the payload.

    @staticmethod
    def _send(proc: subprocess.Popen[bytes], payload: bytes) -> None:
        assert proc.stdin is not None
        proc.stdin.write(struct.pack(">I", len(payload)))
        proc.stdin.write(payload)
        proc.stdin.flush()

    @staticmethod
    def _recv(proc: subprocess.Popen[bytes]) -> bytes:
        assert proc.stdout is not None
        header = proc.stdout.read(4)
        if len(header) != 4:
            err = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
            raise RuntimeError(f"yolo-world worker closed stdout; stderr={err!r}")
        (length,) = struct.unpack(">I", header)
        body = proc.stdout.read(length)
        if len(body) != length:
            raise RuntimeError("yolo-world worker truncated response")
        return body

    # ---- detector API ---------------------------------------------------------

    def detect(self, frame_rgb: bytes, width: int, height: int) -> list[Detection]:
        proc = self._ensure_proc()
        req = WorkerRequest(
            image_b64=base64.b64encode(frame_rgb).decode("ascii"),
            width=width,
            height=height,
            prompt_labels=list(self.config.prompt_labels),
            score_threshold=self.config.score_threshold,
            max_detections=self.config.max_detections,
        )
        self._send(proc, req.model_dump_json().encode("utf-8"))
        raw = self._recv(proc)
        resp = WorkerResponse.model_validate_json(raw)
        if resp.kind != "ok":
            raise RuntimeError(f"yolo-world worker error: {resp.error}")
        return resp.detections

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
        finally:
            self._proc = None
