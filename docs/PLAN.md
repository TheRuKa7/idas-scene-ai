# /ultraplan — iDAS

## Goal
Ship a portfolio-grade open-vocabulary scene-understanding API + demo UI in ~11 working days, pushed to `github.com/TheRuKa7/idas-scene-ai`, with benchmarks and a demo GIF.

## Stack (locked)
- **Runtime:** Python 3.13 (uv), Node 25 (pnpm)
- **Backend:** FastAPI, Pydantic v2, ONNX Runtime, FFmpeg-python, Rich logging
- **Frontend:** Next.js 15 (app router), React 19, Tailwind v4, shadcn/ui, Zustand
- **Models:** YOLO-World (primary), OWLv2 (MIT fallback), ByteTrack
- **Infra:** Docker + docker-compose; GitHub Actions CI
- **Quality:** ruff, mypy, pyright, pytest, vitest (frontend), pre-commit

## Phases

### P0 — Scaffold (Day 1) ✅ done by commit 1
- [x] Directory tree
- [x] `pyproject.toml` with uv, ruff, mypy, pytest
- [x] FastAPI app stub (`/healthz`)
- [x] Dockerfile + docker-compose
- [x] GitHub Actions CI (lint + type + test)
- [x] README, ARCHITECTURE, RESEARCH, PLAN, THINK docs
- [x] `.gitignore` (Python + Node + models)

### P1 — Core detection (Days 2–4)
**Acceptance:** given `samples/street.jpg` and prompts `["pedestrian", "cyclist"]`, API returns bboxes + confidences in <500ms on CPU and renders an overlay.

- [ ] `scripts/download_weights.py` — pull YOLO-World S/M/L and OWLv2 ONNX
- [ ] `models/detector.py` — unified interface, backend switch via `IDAS_LICENSE_MODE`
- [ ] `POST /detect/image` — multipart upload, prompt list, returns JSON + base64 overlay
- [ ] `POST /detect/video` — async job, returns `{job_id, status_url}`
- [ ] `GET /jobs/{id}` — state machine: queued → running → done / failed
- [ ] In-process `asyncio.Queue` with bounded size
- [ ] Unit tests: tensor shapes, NMS correctness, license-mode switch
- [ ] Eval script on COCO val2017 subset (100 images) → mAP@50 sanity

### P2 — Tracking + scene JSON (Days 5–6)
**Acceptance:** 30-second video produces scene JSON with per-track trajectory + entry/exit timestamps.

- [ ] `models/tracker.py` — ByteTrack wrapper
- [ ] `pipeline/video.py` — FFmpeg chunked frame extract (64-frame windows)
- [ ] `pipeline/scene.py` — trajectory aggregation, dwell time, events
- [ ] Scene JSON schema (versioned `scene.v1.schema.json`)
- [ ] Annotated MP4 export (ffmpeg + pillow overlay)

### P3 — Web UI (Days 7–9)
**Acceptance:** user can upload a clip, type a prompt, scrub the timeline, and export results.

- [ ] Next.js scaffold (`create-next-app@latest`)
- [ ] Upload form + progress bar (TanStack Query for polling)
- [ ] `<VideoPlayer />` with canvas overlay driven by scene JSON
- [ ] Timeline scrubber with event markers
- [ ] Prompt input (chips) + "detect" button
- [ ] Export buttons: JSON, annotated MP4
- [ ] Demo GIF recorded via `vhs`/screenkey → committed to `docs/demo.gif`

### P4 — Benchmarks + release (Days 10–11)
**Acceptance:** `docs/BENCHMARKS.md` contains latency + accuracy tables across 3 backends and 3 hardware profiles.

- [ ] `scripts/benchmark.py` — standardized FPS + mAP runs
- [ ] Matrix: YOLO-World S/M/L × CPU/T4/RTX 4090 × ONNX/TensorRT
- [ ] Results table + interpretation paragraph
- [ ] Sample videos committed in `samples/` (< 10MB each)
- [ ] Release v1.0.0 tag + GitHub Release notes
- [ ] Link repo from Rushil's portfolio site + LinkedIn

## Bridges to other portfolio repos
- `POST /scene/query` → proxies to `doc-rag`'s LLM endpoint to answer natural-language questions over scene JSON.
- Shared observability: both repos emit OpenTelemetry traces → common collector doc in `docs/OBSERVABILITY.md` (link-only).

## Risks → mitigations
| Risk | Mitigation |
|------|------------|
| YOLO-World GPL-3 taints MIT repo | Subprocess isolation; OWLv2 fallback; `LICENSE_MODE` flag |
| Long-video OOM | Bounded queue (8 videos), 64-frame chunks, backpressure |
| Open-vocab reproducibility | Pin ODinW splits, fixed seeds, publish eval config |
| ONNX numerical drift | Golden tests vs PyTorch with ±0.5% tolerance |
| Recruiters don't have GPU | CPU-default paths + precomputed sample outputs committed |

## Success criteria
- ✅ README demo GIF under 10 seconds
- ✅ `docker compose up` works cold on a new machine
- ✅ CI green on main; type-check strict
- ✅ At least 3 sample videos + precomputed results committed
- ✅ BENCHMARKS.md with honest numbers (including where we lose)
