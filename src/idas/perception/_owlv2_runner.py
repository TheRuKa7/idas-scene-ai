"""Actual OWLv2 ORT inference helper.

Kept in a separate module so the main OWLv2 detector stays import-safe even
when ORT / numpy / pillow are not installed. The runner is only imported on
the first `detect()` call, after the weights file has been verified to exist.

The implementation below is intentionally minimal — it handles the common
case (single image, text prompts, single detection head) and punts on
TEMPLATE-prompt expansion and image-conditional variants. Swap in the
full-fidelity runner from `scripts/fetch_owlv2.py` before production use.
"""
from __future__ import annotations

from typing import Any

from idas.models.schemas import BBox, Detection


def run_owlv2(
    *,
    session: Any,
    frame_rgb: bytes,
    width: int,
    height: int,
    prompt_labels: list[str],
    score_threshold: float,
    max_detections: int,
) -> list[Detection]:
    """Run OWLv2 forward pass and return normalized-coord detections.

    Raises at runtime if numpy/PIL are not installed — we don't need them
    in CI because the runtime factory picks the stub detector when weights
    are absent.
    """
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    # Decode the raw RGB buffer.
    img = Image.frombytes("RGB", (width, height), frame_rgb)
    # OWLv2 expects 960x960 with normalized pixels.
    img = img.resize((960, 960), Image.Resampling.BILINEAR)
    arr = np.asarray(img, dtype=np.float32) / 255.0
    arr = (arr - np.array([0.485, 0.456, 0.406])) / np.array([0.229, 0.224, 0.225])
    arr = arr.transpose(2, 0, 1)[None]  # NCHW

    # Token-level inputs would normally come from a CLIP text tokenizer. We
    # assume the session was exported with text tokens as a side input; the
    # real runner in scripts/ packages the tokenizer.
    input_feed = {session.get_inputs()[0].name: arr}
    outputs = session.run(None, input_feed)

    # Typical OWLv2 output layout: (logits [N, Q, C], pred_boxes [N, Q, 4]).
    logits, pred_boxes = outputs[0][0], outputs[1][0]
    scores = 1.0 / (1.0 + np.exp(-logits))  # sigmoid

    detections: list[Detection] = []
    for qi in range(scores.shape[0]):
        # Best prompt class for this query.
        ci = int(np.argmax(scores[qi]))
        if ci >= len(prompt_labels):
            continue
        s = float(scores[qi, ci])
        if s < score_threshold:
            continue
        cx, cy, w, h = pred_boxes[qi]
        x1 = float(np.clip(cx - w / 2.0, 0.0, 1.0))
        y1 = float(np.clip(cy - h / 2.0, 0.0, 1.0))
        x2 = float(np.clip(cx + w / 2.0, 0.0, 1.0))
        y2 = float(np.clip(cy + h / 2.0, 0.0, 1.0))
        if x2 <= x1 or y2 <= y1:
            continue
        detections.append(
            Detection(
                label=prompt_labels[ci],
                score=round(s, 4),
                bbox=BBox(x1=x1, y1=y1, x2=x2, y2=y2),
            )
        )

    detections.sort(key=lambda d: d.score, reverse=True)
    return detections[:max_detections]
