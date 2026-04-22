"""YOLO-World subprocess worker.

THIS FILE IS EXECUTED AS A SEPARATE PROCESS. It is never imported from the
iDAS core. It is the only place in the repository that may import Ultralytics
(AGPL / GPL-3). The subprocess boundary is what keeps the main
distribution Apache-2 in terms of symbol visibility.

Protocol (matches `yolo_world.py`):
    parent → child : [u32 BE length][UTF-8 JSON WorkerRequest]
    child → parent : [u32 BE length][UTF-8 JSON WorkerResponse]

The worker lazy-loads the YOLO-World model on the first request so that the
process starts fast even if the first frame is never sent (handy for
readiness probes on the parent side).
"""
from __future__ import annotations

import base64
import json
import struct
import sys
import traceback
from typing import Any

# We intentionally do NOT import from `idas.*` here — the worker is
# stand-alone so it can be vendored into a separately-licensed wheel if a
# downstream user wants to keep even the parent Apache-2 spec files away.

MODEL = None  # lazily created Ultralytics YOLO instance


def _load_model() -> Any:
    global MODEL
    if MODEL is not None:
        return MODEL
    # The import lives inside the function so that a failure to install
    # Ultralytics only poisons the first detect() call, not module load.
    from ultralytics import YOLOWorld  # type: ignore[import-not-found]

    MODEL = YOLOWorld("yolov8s-world.pt")
    return MODEL


def _read_frame() -> bytes:
    header = sys.stdin.buffer.read(4)
    if len(header) != 4:
        raise EOFError("parent closed stdin")
    (length,) = struct.unpack(">I", header)
    body = sys.stdin.buffer.read(length)
    if len(body) != length:
        raise EOFError("truncated frame")
    return body


def _write_frame(payload: bytes) -> None:
    sys.stdout.buffer.write(struct.pack(">I", len(payload)))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def _handle(req: dict[str, Any]) -> dict[str, Any]:
    import numpy as np  # local import for the same isolation reason
    from PIL import Image  # noqa: F401

    model = _load_model()

    # Tell YOLO-World what to look for this frame.
    model.set_classes(req["prompt_labels"])

    raw = base64.b64decode(req["image_b64"])
    w, h = req["width"], req["height"]
    arr = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3)

    results = model.predict(
        arr,
        conf=req["score_threshold"],
        max_det=req["max_detections"],
        verbose=False,
    )[0]

    detections: list[dict[str, Any]] = []
    names = results.names
    for box in results.boxes:
        cls_id = int(box.cls[0])
        label = names[cls_id] if cls_id < len(names) else req["prompt_labels"][cls_id]
        score = float(box.conf[0])
        xyxy = box.xyxyn[0].tolist()  # normalized xyxy directly from Ultralytics
        x1, y1, x2, y2 = xyxy
        detections.append(
            {
                "label": label,
                "score": round(score, 4),
                "bbox": {
                    "x1": max(0.0, min(1.0, float(x1))),
                    "y1": max(0.0, min(1.0, float(y1))),
                    "x2": max(0.0, min(1.0, float(x2))),
                    "y2": max(0.0, min(1.0, float(y2))),
                },
            }
        )

    return {"kind": "ok", "detections": detections, "error": None}


def main() -> None:
    while True:
        try:
            raw = _read_frame()
        except EOFError:
            return
        try:
            req = json.loads(raw.decode("utf-8"))
            resp = _handle(req)
        except Exception as exc:  # noqa: BLE001
            resp = {
                "kind": "error",
                "detections": [],
                "error": f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
            }
        _write_frame(json.dumps(resp).encode("utf-8"))


if __name__ == "__main__":
    main()
