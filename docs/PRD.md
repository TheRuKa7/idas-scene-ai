# PRD — idas-scene-ai

**Owner:** Rushil Kaul · **Status:** P0 scaffold complete, P1 in design · **Last updated:** 2026-04-22

## 1. TL;DR

An open-vocabulary detection + tracking **service** (not a notebook) that lets
operators ask for any object class by natural-language prompt and receive stable
track IDs for analytics and alerting. Ships as a FastAPI microservice with a
sidecar for RTSP ingestion.

## 2. Problem

Closed-class detectors (COCO-only YOLO) force teams into a labelling treadmill for
every new category. Commercial VMS / analytics tools (Bosch, Genetec add-ons) are
expensive, opaque, and lock teams in. Teams need a **self-hosted, promptable
detection layer** that is small enough to read end-to-end.

## 3. Goals

| G | Goal | Measure |
|---|------|---------|
| G1 | Zero-shot detect arbitrary categories by prompt | ≥ mAP-50 of 0.35 on a held-out 20-class eval set |
| G2 | Stable multi-object tracking | ID-switch rate < 5% on MOT17-mini |
| G3 | Production-grade service | p95 latency < 500 ms on T4, uptime 99.5% over 7-day soak |
| G4 | Clear license posture | CI fails if a GPL-3 artefact leaks into `mit-only` mode |
| G5 | 20-minute evaluability | `docker compose up` → working `/detect` in ≤ 90 s cold, ≤ 5 s warm |

## 4. Non-goals

- Training / fine-tuning new detectors (out of scope — see `idas-tune`)
- Identity / face recognition
- Sub-100 ms edge inference
- Multi-tenant SaaS billing

## 5. Users & stakeholders

See `USECASES.md` personas P1–P5. Primary buyer = ops / safety lead; primary
integrator = ML engineer; evaluator = PM. Legal stakeholder reviews license-mode
contract.

## 6. Functional requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| F1  | `POST /detect` accepts image URL + prompts, returns detections | P0 |
| F2  | `POST /detect/batch` accepts video URL + prompts, returns per-frame detections + tracks | P1 |
| F3  | `POST /streams` registers an RTSP source with rules; `DELETE /streams/{id}` removes | P2 |
| F4  | Pluggable detector backends via `BaseDetector` protocol (YOLO-World, Grounding DINO, OWLv2) | P1 |
| F5  | Pluggable tracker backends (ByteTrack, BoT-SORT, OC-SORT) | P2 |
| F6  | Below-trust-threshold detections returned with `below_trust_threshold=true`, never dropped silently | P0 |
| F7  | License-mode startup gate (`standard` / `mit-only`) with clear error | P0 |
| F8  | Prompt audit log (every prompt logged with hash, latency, detection counts) | P1 |
| F9  | Webhook sink on rule match (Slack, generic HTTP, S3 clip) | P2 |
| F10 | Replay endpoint: given `request_id`, return exact same output (determinism in batch mode) | P2 |

## 7. Non-functional requirements

| Category | Requirement |
|----------|-------------|
| Performance | p50 < 200 ms, p95 < 500 ms on T4; batch throughput ≥ 8 FPS on 1080p |
| Availability | 99.5% monthly on self-hosted single-instance deploy (excluding GPU host failures) |
| Security | No inbound writes without API key; RTSP creds encrypted at rest |
| Privacy | No frame persisted beyond 24 h unless explicitly flagged by a rule |
| Observability | OpenTelemetry traces, Prometheus metrics, structured logs (JSON) |
| Licensing | `mit-only` mode proven by CI; SBOM generated per release |
| Deployability | Single `docker compose up`; k8s Helm chart in P3 |

## 8. Success metrics

- **Primary:** detections/week from live-deployed instances (self-reported via opt-in telemetry)
- **Secondary:** repo stars, PRs adding backends, /healthz uptime in the reference demo
- **Quality:** eval-set mAP-50 regression < 2 points across weight upgrades
- **Ops:** mean-time-to-alert for rule matches on RTSP streams

## 9. Milestones

| Phase | Deliverable | ETA |
|-------|-------------|-----|
| P0 | Scaffold + /healthz + /detect stub + license-mode gate + CI | shipped |
| P1 | Real YOLO-World inference + eval harness + prompt audit log | +2 weeks |
| P2 | Tracking + batch video + RTSP sidecar + webhook sinks | +4 weeks |
| P3 | Helm chart + replay endpoint + multi-backend matrix | +6 weeks |

## 10. Dependencies

- PyTorch 2.5, `ultralytics` (for YOLO-World loader), `bytetrack` or `supervision`
- ONNX Runtime for portable inference path
- Optional: Grounding DINO weights, OWLv2 weights (license per backend)

## 11. Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| YOLO-World weights are GPL-3 | Certain | License contamination | `mit-only` mode + CI gate; backend registry declares license explicitly |
| Open-vocab detectors hallucinate on adversarial prompts | High | Trust erosion | `below_trust_threshold` flag + prompt audit + nightly adversarial eval |
| GPU scarcity / cost | Med | Slow inference | CPU fallback path with ONNX int8; advertised perf honest |
| RTSP flakiness in real stores | High | Missed alerts | Auto-reconnect + jitter-tolerant buffer + health probe per stream |
| Privacy complaints on stored clips | Med | Legal | Default TTL = 24 h; configurable; signed-URL access only |

## 12. Open questions

- Do we bake in a Gradio demo page or keep UI out-of-repo? **Leaning: Gradio behind `--demo` flag, default off.**
- Ship a CLIP-based zero-shot classifier as a "tiny" backend for CPU-only users? TBD in P3.
- How do we price the hosted demo (if we offer one)? Likely free tier via Modal / Runpod with quota.
