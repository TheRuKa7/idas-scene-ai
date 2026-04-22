"""One-shot detection endpoint — image in, detections out."""
from __future__ import annotations

import base64
import binascii
import time

from fastapi import APIRouter, HTTPException
from PIL import Image, UnidentifiedImageError
from io import BytesIO

from idas.api.deps import make_detector
from idas.models.schemas import DetectRequest, DetectResponse

router = APIRouter(tags=["detect"])


@router.post("/detect", response_model=DetectResponse)
async def detect(req: DetectRequest) -> DetectResponse:
    """Decode → detect → return. Tracker is *not* applied here.

    The mobile client uses this for stateless previews. Live streams go
    through the stream pipeline instead.
    """
    try:
        raw = base64.b64decode(req.image_b64, validate=True)
    except binascii.Error as exc:
        raise HTTPException(status_code=400, detail=f"invalid base64: {exc}")

    try:
        img = Image.open(BytesIO(raw)).convert("RGB")
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=400, detail=f"invalid image: {exc}")

    detector = make_detector(list(req.prompt_labels))
    try:
        frame_bytes = img.tobytes()
        t0 = time.perf_counter()
        detections = detector.detect(frame_bytes, img.width, img.height)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return DetectResponse(
            detections=detections,
            latency_ms=round(latency_ms, 2),
            detector=detector.name,
            detector_license=detector.license_tag.value,
        )
    finally:
        detector.close()
