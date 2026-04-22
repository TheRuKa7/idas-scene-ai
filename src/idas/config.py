"""Application configuration."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """iDAS runtime settings, loaded from env + .env."""

    model_config = SettingsConfigDict(env_prefix="IDAS_", env_file=".env")

    # License-mode switch: `standard` permits YOLO-World (GPL-3 via subprocess);
    # `mit-only` forces the OWLv2 Apache-2 backend.
    license_mode: Literal["standard", "mit-only"] = "standard"

    # Paths
    weights_dir: Path = Field(default=Path("weights"))
    data_dir: Path = Field(default=Path("data"))

    # Queue
    max_concurrent_jobs: int = 8
    frame_chunk_size: int = 64

    # API
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: Literal["debug", "info", "warning", "error"] = "info"


settings = Settings()
