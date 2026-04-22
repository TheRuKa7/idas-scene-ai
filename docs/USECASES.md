# USECASES — idas-scene-ai

End-to-end narratives for an open-vocabulary detection + tracking service. Each
flow is grounded in a concrete persona and terminates in a measurable outcome.

## 1. Personas

| ID | Persona | Context | Primary JTBD |
|----|---------|---------|--------------|
| P1 | **Retail ops analyst (Maya)** | Runs 12 convenience stores; wants queue/dwell analytics without a $40k/yr SaaS | "Tell me how many people stood at the deli counter for >2 min yesterday" |
| P2 | **Warehouse safety lead (Darius)** | DC with 300 staff; needs forklift-vs-pedestrian near-miss alerts | "Ping me on Slack when a forklift comes within 2 m of a person in Aisle 7" |
| P3 | **Independent ML engineer (Priya)** | Building a custom analytics product; wants a detection API she can hit by URL + prompt | "Give me boxes for 'yellow hard-hat' without training a new model" |
| P4 | **PM evaluator (Rohan)** | Scoping whether to buy vs build open-vocab perception for his team | "Show me the repo runs, the numbers, and the license surface in 20 minutes" |
| P5 | **Security researcher (Elena)** | Red-teaming CV models for spurious-prompt failures | "Can I make the model hallucinate 'knife' with an adversarial prompt?" |

## 2. Jobs-to-be-done

JTBD-1. **Detect arbitrary categories** by natural-language prompt without retraining.
JTBD-2. **Track detections across frames** with stable track IDs for dwell/queue analytics.
JTBD-3. **Expose detections as JSON over HTTP** so downstream dashboards can consume.
JTBD-4. **Stream results from an RTSP camera** for near-real-time alerting.
JTBD-5. **Replay the same video** deterministically for incident investigation.
JTBD-6. **Isolate GPL-licensed weights** so MIT consumers of the repo aren't infected.

## 3. End-to-end flows

### Flow A — Maya runs overnight dwell analytics

1. Maya uploads `store-03-2026-04-21.mp4` to the batch endpoint with
   `prompts=["person","deli counter"]`.
2. Service runs YOLO-World at 6 FPS on a rented T4 (3 min of compute for 8 h video).
3. ByteTrack stitches detections into tracks; dwell time computed per `track_id`
   in a user-drawn polygon (the deli counter).
4. Service returns JSON: `[{track_id, class, dwell_seconds, polygon_hits}]`.
5. Maya pipes into Metabase; morning report shows 14 dwell events >2 min.

### Flow B — Darius gets a forklift near-miss alert

1. RTSP URL registered: `rtsp://cam-aisle-7.local/stream`, prompts
   `["person","forklift"]`, distance rule `min_distance_m(person, forklift) < 2`.
2. Service pulls frames at 10 FPS, runs detection + tracking continuously.
3. On rule breach, posts to Slack webhook with a 5-second video clip + bounding-box overlay.
4. Darius acks; event logged to `incidents/` table with video pointer for OSHA review.

### Flow C — Priya hits the API as an SDK user

```python
import httpx
r = httpx.post("https://idas.example.com/detect",
               json={"image_url": "https://.../frame.jpg",
                     "prompts": ["yellow hard-hat", "person"]})
# r.json() -> {"detections": [{"bbox":[...], "label":"yellow hard-hat", "score":0.82}]}
```

Latency ≤ 400 ms p95 on a warm T4. No retraining, no per-class dataset.

### Flow D — Rohan evaluates the repo in 20 minutes

1. Reads README → sees stack table, license-mode switch, demo clip.
2. Runs `docker compose up`; service boots in < 90 s.
3. Curls `/healthz` → 200, then `/detect` with a sample image → JSON back.
4. Opens `docs/THINK.md` for the PM rationale: why open-vocab, how GPL-3
   weights are isolated, what failure modes exist.
5. Writes his buy/build memo citing exact repo paths.

### Flow E — Elena probes prompt-driven failure modes

1. Sends image of a banana with prompt `["knife"]` → service returns low-confidence
   box (score < 0.3) flagged `below_trust_threshold=true`.
2. Tries `["smallest knife in the universe"]` → same image, sees the model attempt
   a detection; this is logged in `telemetry/prompt_audit.jsonl`.
3. Files an issue; repo ships a prompt-sanitiser middleware in the next release.

### Flow F — Contributor swaps YOLO-World for Grounding DINO

1. Clones repo, checks `src/idas/models/`.
2. Implements `GroundingDinoDetector(BaseDetector)` conforming to the protocol.
3. Updates `config.DETECTOR_BACKEND=grounding_dino`.
4. `uv run pytest` passes; PR merged without touching the API or tracker.

## 4. Acceptance scenarios (Gherkin-lite)

```gherkin
Scenario: Unknown class via prompt returns a box
  Given the service is healthy
  When I POST /detect with image=cafe.jpg and prompts=["espresso machine"]
  Then I receive at least 1 detection with label "espresso machine"
  And the score is >= 0.4
  And the response p95 latency is <= 500 ms on warm GPU

Scenario: License-mode "mit-only" refuses GPL weights
  Given LICENSE_MODE=mit-only
  When the service starts with DETECTOR_BACKEND=yolo_world
  Then startup fails with a clear error citing the offending weights license
  And the process exits non-zero

Scenario: Track IDs persist across frames
  Given a 10-second clip with one continuously visible person
  When I run the tracker in batch mode
  Then exactly one track_id appears across >= 90% of frames

Scenario: RTSP disconnect auto-recovers
  Given an RTSP stream that drops for 30 seconds
  When connectivity is restored
  Then the service resumes detection within 5 seconds without manual restart

Scenario: Below-trust detections are flagged, not dropped
  When a detection is returned with score < trust_threshold
  Then the response marks it below_trust_threshold=true
  And it is logged for eval review
```

## 5. Non-use-cases (intentionally out of scope)

- Face recognition / identity matching (adds GDPR Art. 9 burden)
- Sub-100 ms latency (edge inference is a separate fork)
- Training new detectors (fine-tune track lives in `idas-tune`, not here)
- Audio analytics
