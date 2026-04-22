"""Pydantic schemas shared by the HTTP API and the internal pipeline.

All geometry is expressed in normalized image coordinates (0..1) unless a
comment says otherwise. Keeping a single unit avoids the class of bugs where
frame A's detector returns pixels and frame B's rule engine assumes ratios.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ----- geometry -----------------------------------------------------------------


class BBox(BaseModel):
    """Axis-aligned box in normalized image coordinates (xyxy)."""

    model_config = ConfigDict(frozen=True)

    x1: float = Field(ge=0.0, le=1.0)
    y1: float = Field(ge=0.0, le=1.0)
    x2: float = Field(ge=0.0, le=1.0)
    y2: float = Field(ge=0.0, le=1.0)

    @field_validator("x2")
    @classmethod
    def _x_order(cls, v: float, info: Any) -> float:
        x1 = info.data.get("x1", 0.0)
        if v < x1:
            raise ValueError(f"x2 ({v}) must be >= x1 ({x1})")
        return v

    @field_validator("y2")
    @classmethod
    def _y_order(cls, v: float, info: Any) -> float:
        y1 = info.data.get("y1", 0.0)
        if v < y1:
            raise ValueError(f"y2 ({v}) must be >= y1 ({y1})")
        return v

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0


class Zone(BaseModel):
    """A named polygon in normalized image coordinates."""

    name: str
    points: list[tuple[float, float]] = Field(min_length=3)


# ----- detection / tracking output ---------------------------------------------


class Detection(BaseModel):
    """A single detection. `label` is free-form text from the prompt set."""

    model_config = ConfigDict(frozen=True)

    label: str
    score: float = Field(ge=0.0, le=1.0)
    bbox: BBox


class Track(BaseModel):
    """A tracked identity across frames."""

    model_config = ConfigDict(frozen=True)

    track_id: int
    label: str
    score: float
    bbox: BBox
    age: int = 0  # number of frames this identity has existed
    hits: int = 0  # number of frames it has been matched


# ----- rule engine --------------------------------------------------------------


RuleOp = Literal["class_in", "in_zone", "dwell_gt", "and", "or", "not"]


class RuleDef(BaseModel):
    """A JSON rule. `op` selects the semantics; `args` holds operands.

    Examples::

        {"op": "class_in", "args": {"labels": ["person"]}}
        {"op": "and", "args": {"clauses": [
            {"op": "class_in", "args": {"labels": ["person"]}},
            {"op": "in_zone", "args": {"zone": "doorway"}},
            {"op": "dwell_gt", "args": {"seconds": 10}}
        ]}}
    """

    op: RuleOp
    args: dict[str, Any] = Field(default_factory=dict)
    name: str | None = None  # optional human label for the rule


class RuleHit(BaseModel):
    """A persisted rule match."""

    id: int | None = None
    stream_id: str
    rule_name: str
    track_id: int
    label: str
    t_start: datetime
    t_end: datetime | None = None
    score: float
    zone: str | None = None
    clip_path: str | None = None


# ----- streams ------------------------------------------------------------------


StreamState = Literal["idle", "starting", "running", "stopped", "errored"]


class StreamCreate(BaseModel):
    """User-supplied stream spec."""

    name: str
    url: str  # rtsp://, http://, or file path
    prompt_labels: list[str] = Field(min_length=1)
    rules: list[RuleDef] = Field(default_factory=list)
    zones: list[Zone] = Field(default_factory=list)


class Stream(StreamCreate):
    """A stream as managed by the service."""

    id: str
    state: StreamState = "idle"
    created_at: datetime
    last_frame_at: datetime | None = None
    error: str | None = None


# ----- API DTOs -----------------------------------------------------------------


class FrameMeta(BaseModel):
    """Optional frame metadata passed with /detect."""

    stream_id: str | None = None
    ts_ms: int | None = None


class DetectRequest(BaseModel):
    """One-shot detection on a base64-encoded image.

    The mobile client posts here; the stream runner invokes the detector
    in-process and never goes through HTTP.
    """

    image_b64: str
    prompt_labels: list[str] = Field(min_length=1)
    meta: FrameMeta | None = None


class DetectResponse(BaseModel):
    detections: list[Detection]
    latency_ms: float
    detector: str
    detector_license: str


class LicenseInfo(BaseModel):
    """Returned by /licenses — describes how the build is configured."""

    mode: Literal["standard", "mit-only"]
    detector: str
    detector_license: str
    tracker: str
    tracker_license: str
    subprocess_isolated: bool
