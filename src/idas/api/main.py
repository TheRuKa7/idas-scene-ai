"""FastAPI entry point.

``uvicorn idas.api.main:app``

Routes are grouped by concern under :mod:`idas.api.routes`. The app holds
no global runner registry — individual streams are managed by the
:class:`StreamRunner` the mobile UI starts on demand.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from idas import __version__
from idas.api.routes import alerts, detect, health, licenses, rules, streams
from idas.config import settings
from idas.storage.database import init_db

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Materialize tables up front so the first request isn't the one that
    # pays the CREATE TABLE tax.
    init_db()
    yield


def create_app() -> FastAPI:
    """App factory — makes testing with overridden deps ergonomic."""
    app = FastAPI(
        title="iDAS",
        version=__version__,
        description=(
            "Open-vocabulary dashcam / CCTV scene understanding. "
            "YOLO-World + ByteTrack + FastAPI. License-mode switch keeps "
            "GPL-3 detectors behind a subprocess boundary."
        ),
        lifespan=_lifespan,
    )

    # CORS: the mobile client talks to the service from `exp://...` in dev.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(licenses.router)
    app.include_router(detect.router)
    app.include_router(streams.router)
    app.include_router(alerts.router)
    app.include_router(rules.router)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "service": "idas",
            "version": __version__,
            "docs": "/docs",
            "repo": "https://github.com/TheRuKa7/idas-scene-ai",
        }

    return app


app = create_app()
