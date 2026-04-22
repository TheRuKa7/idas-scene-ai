# DFD — idas-scene-ai

Data flow diagrams at three levels. External entities are squared, processes are
rounded, data stores are `[[…]]`, data flows are labelled edges.

## Level 0 — Context diagram

```mermaid
flowchart LR
  OPS[Ops user / dashboard]
  SDK[ML engineer / SDK]
  CAM[RTSP camera]
  SINK[Webhook sink<br/>Slack / HTTP / S3]
  IDAS((idas-scene-ai<br/>service))

  OPS -- register stream, view hits --> IDAS
  SDK -- POST /detect (image + prompts) --> IDAS
  IDAS -- JSON detections --> SDK
  CAM -- RTSP frames --> IDAS
  IDAS -- rule-hit payload + clip URL --> SINK
  IDAS -- audit + metrics --> OPS
```

## Level 1 — Internal functional decomposition

```mermaid
flowchart TD
  subgraph Ingress
    API[1.0 API gateway<br/>FastAPI + auth + rate limit]
    STREAM[1.1 Stream ingestor<br/>RTSP -> frames]
  end

  subgraph Processing
    DET[2.0 Detector<br/>YOLO-World / GDINO / OWLv2]
    TRK[2.1 Tracker<br/>ByteTrack / BoT-SORT]
    RULE[2.2 Rule engine<br/>JSON DSL compiler + matcher]
  end

  subgraph Egress
    RESP[3.0 Response assembler]
    WH[3.1 Webhook dispatcher]
    CLIP[3.2 Clip archiver]
  end

  subgraph Stores
    PG[[Postgres<br/>streams / rule_hits / prompt_audit]]
    REDIS[[Redis<br/>job queue + tracker state]]
    S3[[Object store<br/>rule-hit clips]]
  end

  API -- detect req --> DET
  API -- register stream --> PG
  STREAM -- frame + prompts --> DET
  DET -- detections --> TRK
  TRK -- tracks --> RULE
  RULE -- match? --> WH
  RULE -- clip window --> CLIP
  CLIP --> S3
  WH -- signed URL --> S3
  DET -- audit row --> PG
  RULE -- hit row --> PG
  TRK -. snapshot .-> REDIS
  API -- queue job --> REDIS
  RESP --> API
```

## Level 2 — Single-image detect path (hot path)

```mermaid
sequenceDiagram
  autonumber
  participant C as Client
  participant A as API
  participant Q as Redis queue
  participant W as Inference worker
  participant M as Model<br/>(YOLO-World)
  participant P as Postgres
  C->>A: POST /detect (image_url, prompts)
  A->>A: auth + rate-limit + schema
  A->>Q: enqueue(image_url, prompts, req_id)
  W->>Q: dequeue
  W->>W: fetch image via signed URL
  W->>M: detect(img, prompts)
  M-->>W: detections[]
  W->>W: apply trust_threshold flag
  W->>P: insert prompt_audit row
  W-->>A: result (via pubsub)
  A-->>C: 200 { request_id, detections[], latency_ms }
```

## Level 2 — Streaming path with rule hit

```mermaid
sequenceDiagram
  autonumber
  participant R as RTSP Cam
  participant S as Stream worker
  participant D as Detector
  participant T as Tracker
  participant G as Rule engine
  participant K as Clip archiver
  participant H as Webhook
  R->>S: RTP stream (H.264)
  loop every Nth frame
    S->>D: frame
    D->>T: detections
    T->>T: update track state (Redis)
    T->>G: tracks
    alt rule matches
      G->>K: request clip (t-3s .. t+2s)
      K-->>G: signed S3 URL
      G->>H: POST {rule_id, bboxes, clip_url}
      G->>Postgres: insert rule_hit
    end
  end
```

## Data stores

| Store | Purpose | Retention | Sensitivity |
|-------|---------|-----------|-------------|
| Postgres `streams` | Registered RTSP sources + rules | Until deleted by user | High (contains cam URLs — encrypted) |
| Postgres `rule_hits` | Log of rule-match events | 90 days default | Medium |
| Postgres `prompt_audit` | Prompt-text + metrics per request | 30 days default | Low-medium |
| Redis queue | Pending detect jobs | seconds | Low |
| Redis tracker-state | Per-stream tracker snapshot | 30 min TTL | Low |
| S3 clips | Video clips from rule hits | 24 h default, configurable | High (could contain PII) |

## Trust boundaries

```mermaid
flowchart LR
  subgraph Public["Public / untrusted"]
    SDK
    CAM
    OPS
  end
  subgraph PrivateVPC["Private VPC"]
    API_INT[API]
    WORKER[Workers]
    REDIS_INT[Redis]
    PG_INT[Postgres]
  end
  subgraph Partner["Partner-controlled"]
    SINK
  end
  SDK -- HTTPS + API key --> API_INT
  CAM -- RTSP+TLS (preferred) --> WORKER
  OPS -- HTTPS + SSO --> API_INT
  API_INT <--> REDIS_INT
  WORKER <--> REDIS_INT
  WORKER --> PG_INT
  WORKER -- signed URL + HMAC --> SINK
```

## PII / data-minimisation notes

- Raw frames are **not** persisted unless a rule fires.
- Rule-hit clips are retained 24 h by default; signed-URL only.
- Prompt text is retained in `prompt_audit` for eval; a hash-only mode
  (`AUDIT_LEVEL=hash`) exists for privacy-sensitive deploys.
- RTSP URLs (often contain creds) are encrypted with `pgcrypto` and only
  decrypted inside the stream worker's in-memory cache.
