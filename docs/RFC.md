# RFC-001 — idas-scene-ai detection service

**Author:** Rushil Kaul · **Status:** Draft · **Target release:** P1–P2

## 1. Summary

Design the detection + tracking service as a FastAPI app with pluggable
backends (`BaseDetector`, `BaseTracker`) and a sidecar RTSP worker. All I/O is
JSON; video/image ingress via signed URLs; tracking state held in Redis for
horizontal scale of the sidecar only.

## 2. Context

See `RESEARCH.md` for backend comparison (YOLO-World vs Grounding DINO vs OWLv2
vs RT-DETR) and `PRD.md` for requirements. This RFC pins the architecture.

## 3. Detailed design

### 3.1 Component inventory

| Component | Lang/Runtime | Role |
|-----------|--------------|------|
| `api` | Python 3.13 / FastAPI / Uvicorn | HTTP surface, auth, rate limit |
| `worker-infer` | Python / PyTorch / ONNX-RT | Runs detector on a GPU; pulls from `jobs` queue |
| `worker-stream` | Python / OpenCV / FFmpeg | Pulls RTSP, decimates, pushes frames to inference |
| `tracker-svc` | Python / ByteTrack | In-process with `worker-infer`; state in Redis for resume |
| `redis` | Redis 7 | Job queue + per-stream tracker state TTL=30 min |
| `postgres` | Postgres 16 | Rule definitions, audit log, incident records |
| `object-store` | S3 / R2 | Clip archive for rule hits (signed URLs) |

### 3.2 Backend protocols

```python
class BaseDetector(Protocol):
    name: str
    license: Literal["MIT", "Apache-2.0", "GPL-3.0", "Custom"]

    def load(self, weights_path: Path) -> None: ...
    def detect(self, image: np.ndarray, prompts: list[str]) -> list[Detection]: ...

class BaseTracker(Protocol):
    name: str
    def update(self, detections: list[Detection], frame_idx: int) -> list[Track]: ...
    def snapshot(self) -> bytes: ...   # serialisable state
    def restore(self, blob: bytes) -> None: ...
```

License field enforces the mode gate at startup:

```python
def _assert_license_compatible(det: BaseDetector, mode: Literal["standard","mit-only"]) -> None:
    if mode == "mit-only" and det.license in {"GPL-3.0", "AGPL-3.0"}:
        raise LicenseIncompatible(f"{det.name}: {det.license} not allowed in mit-only mode")
```

### 3.3 Core API contract

```
POST /detect
  body: { "image_url": str, "prompts": [str], "trust_threshold"?: float }
  200 : { "request_id": uuid, "detections": [Detection], "latency_ms": int, "backend": str }
  4xx : { "error": str, "code": enum }

POST /detect/batch
  body: { "video_url": str, "prompts": [str], "sample_fps"?: int, "rules"?: [Rule] }
  202 : { "job_id": uuid, "status_url": str }
  (then) GET /jobs/{job_id} -> status + paginated results

POST /streams
  body: { "rtsp_url": str, "prompts": [str], "rules": [Rule], "webhook_url"?: str }
  201 : { "stream_id": uuid }

DELETE /streams/{stream_id}  -> 204

GET /healthz                  -> 200 { "backend": str, "device": str, "license_mode": str }
GET /metrics                  -> Prometheus text
```

### 3.4 Data model

Postgres schema (key tables):

```sql
CREATE TABLE streams (
  id uuid PRIMARY KEY,
  rtsp_url_enc bytea NOT NULL,           -- encrypted at rest (pgcrypto)
  prompts text[] NOT NULL,
  rules jsonb NOT NULL,
  webhook_url text,
  created_at timestamptz DEFAULT now(),
  status text CHECK (status IN ('active','paused','errored'))
);

CREATE TABLE rule_hits (
  id uuid PRIMARY KEY,
  stream_id uuid REFERENCES streams(id),
  rule_id text NOT NULL,
  at timestamptz NOT NULL,
  payload jsonb NOT NULL,                -- boxes, track_ids, metric
  clip_url text,                         -- signed S3 URL (TTL)
  acked_by text
);

CREATE TABLE prompt_audit (
  id bigserial PRIMARY KEY,
  prompt_hash text NOT NULL,
  prompt_text text NOT NULL,
  at timestamptz DEFAULT now(),
  backend text NOT NULL,
  latency_ms int,
  detection_count int,
  below_trust_count int
);
```

### 3.5 Rule language (v1)

JSON DSL (keep it boring):

```json
{
  "id": "forklift_near_person",
  "when": {
    "all": [
      { "class_present": "person" },
      { "class_present": "forklift" }
    ]
  },
  "predicate": { "min_distance_m": {"a":"person","b":"forklift","lt":2.0}},
  "cooldown_s": 10,
  "clip_seconds_before": 3,
  "clip_seconds_after": 2
}
```

Rules are compiled to small Python callables at registration; no eval of
arbitrary code. Predicates are a closed whitelist in v1.

### 3.6 License-mode gate

- `LICENSE_MODE=mit-only` (default) disallows GPL/AGPL backends.
- CI job `license-matrix.yml` boots the service in both modes against a fixture
  backend registry; asserts both behaviours match the contract.
- SBOM generated via `cyclonedx-py` on each release.

### 3.7 Observability

- Traces: OTEL — span per request, child spans per detect/track/webhook.
- Metrics: Prometheus — `idas_request_latency_ms{endpoint,backend}`,
  `idas_detections_total{backend,class}`, `idas_stream_up{stream_id}`.
- Logs: JSON lines, `request_id` bound via context var.
- Dashboard: Grafana JSON committed under `ops/grafana/`.

## 4. Alternatives considered

| Alt | Why not |
|-----|---------|
| Go service with Python inference over gRPC | Adds ops complexity for negligible latency win in P1 |
| Triton Inference Server | Overkill until we have >3 backends in prod; revisit in P3 |
| Celery + RabbitMQ instead of Redis queue | Redis streams are simpler and sufficient for expected job rate |
| NATS JetStream for streaming | Possibly better long-term; defer until multi-tenant is on the roadmap |
| Per-class fine-tuned YOLO | Contradicts the open-vocab thesis |

## 5. Tradeoffs

- **Python end-to-end** — easier contribution, single language. Cost: GIL on the
  inference path; mitigated by GPU being the bottleneck anyway.
- **JSON rules, no DSL** — simpler, but expressivity is limited. Will add a
  WASM-sandboxed user-function hook in P3 if demand materialises.
- **Redis for tracker state** — cheap horizontal scale, but state is ephemeral.
  For compliance-grade "record of sensor history" we'd write to TimescaleDB.

## 6. Rollout plan

1. Ship `/detect` + license gate + prompt audit (P1, week 1–2).
2. Add batch endpoint + eval harness + CI perf budget (P1, week 2–3).
3. Add tracker + stream sidecar + rule engine + webhooks (P2, week 4–5).
4. Helm chart + replay endpoint + multi-backend matrix (P3, week 6).
5. Beta with one friendly design partner (retail or warehouse).

## 7. Open questions

- Do we need per-prompt embedding cache? Likely yes for high-QPS scenarios.
- Clip archive TTL — 24 h default, but retail may want 14 days. Per-stream config.
- WebRTC output for hosted-demo page — nice UX, but non-trivial; post-P3.
