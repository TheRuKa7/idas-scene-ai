"""End-to-end API tests: health, licenses, detect, streams CRUD, rules."""
from __future__ import annotations

import base64
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from idas.api.main import create_app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert body["license_mode"] in {"standard", "mit-only"}


def test_root(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["service"] == "idas"


def test_licenses_endpoint_reports_stub_in_force_mode(client: TestClient) -> None:
    r = client.get("/licenses")
    assert r.status_code == 200
    body = r.json()
    # conftest sets IDAS_FORCE_STUB=1, so we must be on the stub path.
    assert body["detector"] == "stub"
    assert body["detector_license"] == "Apache-2.0"
    assert body["tracker"] == "bytetrack"
    assert body["tracker_license"] == "MIT"
    assert body["subprocess_isolated"] is False


def _png_b64(color: tuple[int, int, int] = (200, 50, 50)) -> str:
    img = Image.new("RGB", (32, 32), color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_detect_endpoint_happy_path(client: TestClient) -> None:
    r = client.post(
        "/detect",
        json={"image_b64": _png_b64(), "prompt_labels": ["person", "car"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["detector"] == "stub"
    assert body["detector_license"] == "Apache-2.0"
    assert isinstance(body["detections"], list)
    # Stub returns one detection per label.
    assert len(body["detections"]) <= 2
    for d in body["detections"]:
        assert set(d["bbox"].keys()) == {"x1", "y1", "x2", "y2"}
        for coord in d["bbox"].values():
            assert 0.0 <= coord <= 1.0


def test_detect_rejects_bad_base64(client: TestClient) -> None:
    r = client.post(
        "/detect", json={"image_b64": "!!!not-base64!!!", "prompt_labels": ["x"]}
    )
    assert r.status_code == 400


def test_detect_rejects_non_image(client: TestClient) -> None:
    r = client.post(
        "/detect",
        json={
            "image_b64": base64.b64encode(b"definitely not an image").decode("ascii"),
            "prompt_labels": ["x"],
        },
    )
    assert r.status_code == 400


def test_streams_crud(client: TestClient) -> None:
    # Create
    r = client.post(
        "/streams",
        json={
            "name": "front-door",
            "url": "rtsp://example/front",
            "prompt_labels": ["person", "package"],
            "rules": [
                {
                    "op": "class_in",
                    "name": "pkg_present",
                    "args": {"labels": ["package"]},
                }
            ],
            "zones": [
                {
                    "name": "porch",
                    "points": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    stream = r.json()
    sid = stream["id"]
    assert stream["state"] == "idle"

    # List
    r2 = client.get("/streams")
    assert r2.status_code == 200
    ids = [s["id"] for s in r2.json()]
    assert sid in ids

    # Get
    r3 = client.get(f"/streams/{sid}")
    assert r3.status_code == 200
    assert r3.json()["name"] == "front-door"

    # 404 on missing
    r4 = client.get("/streams/does-not-exist")
    assert r4.status_code == 404

    # Delete
    r5 = client.delete(f"/streams/{sid}")
    assert r5.status_code == 204
    r6 = client.get(f"/streams/{sid}")
    assert r6.status_code == 404


def test_alerts_empty_for_new_stream(client: TestClient) -> None:
    r = client.get("/alerts")
    assert r.status_code == 200
    assert r.json() == []


def test_rule_validation_ok(client: TestClient) -> None:
    r = client.post(
        "/rules/validate",
        json={
            "op": "and",
            "name": "person_in_porch",
            "args": {
                "clauses": [
                    {"op": "class_in", "args": {"labels": ["person"]}},
                    {"op": "in_zone", "args": {"zone": "porch"}},
                ]
            },
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_rule_validation_rejects_bad_rule(client: TestClient) -> None:
    r = client.post(
        "/rules/validate",
        json={"op": "class_in", "args": {"labels": []}},
    )
    assert r.status_code == 400
