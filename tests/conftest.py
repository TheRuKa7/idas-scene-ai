"""Shared test fixtures.

We force the deterministic stub detector everywhere so CI never tries to
load ONNX weights or spawn a YOLO-World subprocess. Individual license-mode
tests set env vars explicitly — they override this.
"""
from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# Set BEFORE importing idas so settings picks it up on first access.
os.environ.setdefault("IDAS_FORCE_STUB", "1")
_tmp_data = tempfile.mkdtemp(prefix="idas-test-")
os.environ.setdefault("IDAS_DATA_DIR", _tmp_data)


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point every test at its own SQLite file + reset the cached engine."""
    db_url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    monkeypatch.setenv("IDAS_DB_URL", db_url)
    from idas.storage.database import reset_engine_for_tests

    reset_engine_for_tests()
    yield
    reset_engine_for_tests()
