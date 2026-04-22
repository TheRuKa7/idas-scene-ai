# iDAS — Intelligent Detection & Analysis System

> **Open-vocabulary dashcam / CCTV scene understanding.** Upload video, describe what you're looking for in plain English, get tracked scene JSON and an annotated overlay.

[![CI](https://github.com/TheRuKa7/idas-scene-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/TheRuKa7/idas-scene-ai/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Built by [Rushil Kaul](https://github.com/TheRuKa7) — a portfolio rebuild of a 2022 YOLO project, re-architected around open-vocabulary detection (YOLO-World), tracking (ByteTrack), and an async FastAPI pipeline.

---

## Highlights

- **Open-vocabulary** — detect any class via text prompt, no retraining
- **Tracking + scene JSON** — entry/exit events, dwell time, trajectories
- **Async video pipeline** — FastAPI background jobs + FFmpeg
- **Web UI** — Next.js 15 app with timeline scrubber and prompt input
- **ONNX inference** — runs on CPU laptops; GPU path optional
- **Bench-backed** — COCO mAP, LVIS AR, ODinW open-vocab, wall-clock FPS

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md). High-level: video → frame-extract → YOLO-World detection → ByteTrack → scene aggregation → JSON + overlay.

## Docs

| Doc | Purpose |
|-----|---------|
| [docs/RESEARCH.md](./docs/RESEARCH.md) | SOTA detection landscape, model comparison |
| [docs/PLAN.md](./docs/PLAN.md) | Phased implementation plan, acceptance criteria |
| [docs/THINK.md](./docs/THINK.md) | Design rationale, tradeoffs, risks, PM framing |
| [docs/BENCHMARKS.md](./docs/BENCHMARKS.md) | Latency, accuracy, model zoo results |

## Quickstart

```bash
# Python backend
uv sync
uv run python scripts/download_weights.py
uv run uvicorn idas.api.main:app --reload

# Frontend
cd frontend && pnpm install && pnpm dev
```

Test the API:
```bash
curl -X POST http://localhost:8000/detect/image \
  -F "image=@samples/street.jpg" \
  -F "prompts=pedestrian,cyclist,traffic cone"
```

## Status

🚧 Active development — see [milestones](https://github.com/TheRuKa7/idas-scene-ai/milestones) and [ROADMAP.md](./ROADMAP.md).

## License

MIT. Note: the optional YOLO-World backend is GPL-3 — invoked as a subprocess, not linked. Set `IDAS_LICENSE_MODE=mit-only` to fall back to OWLv2 (Apache-2).
