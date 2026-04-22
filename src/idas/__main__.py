"""`python -m idas` — start uvicorn with settings from :mod:`idas.config`."""
from __future__ import annotations

import uvicorn

from idas.config import settings


def main() -> None:
    uvicorn.run(
        "idas.api.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
