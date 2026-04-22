"""Smoke tests — exercise the scaffold before real features land."""
from __future__ import annotations

from fastapi.testclient import TestClient

from idas import __version__
from idas.api.main import app

client = TestClient(app)


def test_healthz() -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


def test_root() -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["service"] == "idas"
