"""Liveness / readiness probes."""
from __future__ import annotations

from fastapi import APIRouter

from idas import __version__
from idas.config import settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness. Returns immediately."""
    return {
        "status": "ok",
        "version": __version__,
        "license_mode": settings.license_mode,
    }


@router.get("/readyz")
async def readyz() -> dict[str, str]:
    """Readiness — same shape as healthz for now, extended later with DB ping."""
    return {"status": "ready", "version": __version__}
