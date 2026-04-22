# /ultrathink — iDAS

*Design rationale, tradeoffs, risks, and why this repo is portfolio-strong. Written for Rushil's interviewers to read, not just for the code.*

## 1. Why rebuild this project at all?

The 2022 iDAS was a student project: fixed COCO classes, a Colab notebook, a screenshot. That doesn't move the needle in 2026 when hiring managers have already seen thousands of YOLO demos.

**The rebuild moves three levers:**
1. **Open-vocabulary** — prompt-driven, not retraining-driven. This is the 2024+ shift in CV.
2. **End-to-end** — model + API + UI + eval + CI + Docker + benchmarks, not a notebook.
3. **Licensing & production hygiene** — subprocess isolation, bounded queues, OpenTelemetry hooks. Rare signal in ML portfolios.

## 2. Why these model choices?

**YOLO-World over YOLOv10:** v10 is faster, but closed-vocab. For a demo you want to record once and show to anyone — open-vocab lets the recruiter type their own prompt and see it work. That's a 10× stronger narrative than showing "I trained on 80 classes."

**OWLv2 as the MIT fallback:** signals license-awareness, which is disproportionately valuable. Most ML portfolios ignore licensing entirely — mentioning it in a README flags you as someone who's thought about shipping, not just training.

**ByteTrack over BoT-SORT:** ByteTrack wins on the speed/simplicity Pareto. BoT-SORT is better on MOT17 IDF1 but requires ReID features, which couple you to specific detectors. For open-vocab where detections are class-flexible, ByteTrack's motion-only approach degrades more gracefully.

## 3. PM framing (for interviews)

This is where Rushil's PM background becomes a differentiator — most AI Eng candidates can't articulate a product story.

- **Problem:** Fleet operators want ad-hoc scene queries ("show me every time someone jaywalked"), but existing dashcam AI only detects preset classes. Getting a new class takes weeks of labeling + retraining.
- **User:** Fleet safety manager, insurance claims adjuster, traffic planner.
- **Metric:** Query satisfaction rate (did we find what they asked for?), P95 latency per query, false-positive rate per hour of video.
- **Wedge:** Open-vocab drops marginal cost of a new detection need from "$5k + 2 weeks" to "$0 + 10 seconds."
- **Monetization:** Per-query API pricing + per-minute-of-video processing tier.
- **Why now:** YOLO-World class of models hit production-viable latency in 2024; vector + LLM infra is now affordable enough to bolt on scene-level Q&A.

## 4. Key tradeoffs (decided)

| Decision | Alternatives | Why chosen |
|----------|-------------|------------|
| FastAPI over Flask | Django, Starlette | Async-native, Pydantic-native, minimal overhead |
| ONNX over PyTorch-serve | TorchServe, Triton | Portability; recruiters on laptops |
| Next.js over plain React | Vite+React, Remix | SSR for demo page SEO; app-router modern |
| uv over poetry/pip | poetry, rye | Speed + lock discipline; future-proof choice |
| Local FS over S3 for v1 | R2, S3, MinIO | Zero-friction repro; S3 in v2 |
| In-process queue over Redis | Celery, RQ, Dramatiq | Simpler repo; Redis in v2 |
| Monorepo (BE + FE) | Two repos | Tighter review, one README |

## 5. Key tradeoffs (deferred)

- **Dashcam finetuning on BDD100K:** probably v2. Adds real domain fit but adds 2-3 days + a training pipeline. Ship with zero-shot first; add finetuning if a recruiter asks "how would you improve accuracy?"
- **Browser inference via WebGPU:** YOLO-World ONNX is ~200MB; too heavy for typical first-paint budgets. Revisit when model distillation improves.
- **Multi-tenancy / auth:** out of scope for portfolio. Comment in README that prod version would add OIDC + rate limits.

## 6. Risks (ranked)

1. **Licensing leak** — if I accidentally link GPL-3 YOLO-World weights into MIT-licensed Python code, the whole repo becomes GPL. *Mitigation: subprocess boundary + doc + `LICENSE_MODE` flag + CI check that blocks `import ultralytics` outside `backends/yolo_world/`.*
2. **Recruiter can't run it** — if Docker image is 5GB or requires GPU, nobody tries the demo. *Mitigation: CPU-default, < 2GB image, precomputed sample outputs committed.*
3. **Benchmark theater** — cherry-picked FPS numbers would get torn apart in an AI Eng interview. *Mitigation: publish the script, pin seeds, include failure modes, show where we lose.*
4. **Scope creep via "scene Q&A"** — easy to spend a week building the LLM layer. *Mitigation: `scene/query` is a stub in v1 that proxies to `doc-rag`; real Q&A lives in that repo.*
5. **Tracking regression on prompt change** — if user changes prompts mid-video, track IDs reset badly. *Mitigation: document it as a known limitation; v2 adds class-agnostic ReID.*

## 7. What makes this portfolio-strong (specifically)

Things recruiters will notice in order of importance:

1. **Demo GIF works in README** — 80% of portfolio repos don't have one
2. **`docker compose up` produces a running app** — 90% don't work
3. **Honest benchmarks including losses** — 99% don't publish them at all
4. **License-mode switch** — 99.9% ignore this entirely
5. **Mermaid architecture diagram** — raises perceived seriousness instantly
6. **PM framing in THINK.md** — makes Rushil's hybrid background a feature

## 8. What I'd do differently in v2

- Dashcam-specific finetuning on BDD100K + nuScenes
- WebGPU browser inference (maybe with distilled models)
- Real-time RTSP stream support (for CCTV)
- Integration with [`doc-rag`](../doc-rag) for natural-language scene Q&A
- A proper job queue (Redis + RQ) and multi-worker GPU pool
- Auth + per-user rate limiting for the public demo

## 9. Interview talking points (cheat sheet)

- *"Why open-vocab?"* — zero marginal cost for a new class; product flexibility.
- *"Why not train our own?"* — time-to-value; transfer learning from CLIP is the point.
- *"How would you scale?"* — horizontal workers, GPU pool, chunked reads, object storage.
- *"What's your eval strategy?"* — ODinW for open-vocab generalization, MOT17 for tracking, domain holdout for dashcam specifics.
- *"What's the limitation?"* — latency (~10-15ms/frame) still cloud-only for real-time 60fps; edge needs distillation.
