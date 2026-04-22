"""FastAPI entry point."""
from __future__ import annotations

from fastapi import FastAPI

from idas import __version__
from idas.config import settings

app = FastAPI(
    title="iDAS",
    version=__version__,
    description="Open-vocabulary dashcam / CCTV scene understanding",
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "version": __version__, "license_mode": settings.license_mode}


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "idas",
        "version": __version__,
        "docs": "/docs",
        "repo": "https://github.com/TheRuKa7/idas-scene-ai",
    }


# NOTE: detection + job routes are implemented in P1.
# See docs/PLAN.md for the phased rollout.
