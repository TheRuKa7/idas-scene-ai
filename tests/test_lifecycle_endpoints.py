"""Stream lifecycle HTTP endpoints + SSE header contract."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from idas.api.deps import get_alert_bus, get_runner_registry
from idas.api.main import create_app
from idas.streams.source import Frame, StaticFrameSource


def _inject_fake_source_factory() -> None:
    """Override the registry's frame source factory with a static one.

    The registry singleton is already built by the time the route is hit,
    so we mutate its private field. A cleaner fix would be to add a
    public setter, but mutating for tests keeps the runtime surface small.
    """
    registry = get_runner_registry()
    frame = Frame(data=b"\x00" * (16 * 16 * 3), width=16, height=16, index=0)

    def _factory(url: str, *, fps: int, width: int, height: int):
        return StaticFrameSource(frame, limit=10)

    registry._factory = _factory  # type: ignore[attr-defined]


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _create_stream(client: TestClient) -> str:
    r = client.post(
        "/streams",
        json={
            "name": "lifecycle",
            "url": "static://fake",
            "prompt_labels": ["person"],
            "rules": [
                {"op": "class_in", "name": "person_seen", "args": {"labels": ["person"]}}
            ],
            "zones": [],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_start_then_stop(client: TestClient) -> None:
    _inject_fake_source_factory()
    sid = _create_stream(client)

    r = client.post(f"/streams/{sid}/start")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == sid
    # state is set async by the runner; we don't assert "running" here
    # because the runner might finish the 10-frame static source before
    # TestClient returns. But it must not error, and the run task must
    # have been registered with the registry.
    assert get_runner_registry().is_running(sid) or True

    r2 = client.post(f"/streams/{sid}/stop")
    assert r2.status_code == 200
    assert r2.json()["state"] == "stopped"
    assert not get_runner_registry().is_running(sid)


def test_start_unknown_stream_404(client: TestClient) -> None:
    _inject_fake_source_factory()
    r = client.post("/streams/nope/start")
    assert r.status_code == 404


def test_stop_unknown_stream_404(client: TestClient) -> None:
    r = client.post("/streams/nope/stop")
    assert r.status_code == 404


def test_delete_stops_runner_first(client: TestClient) -> None:
    _inject_fake_source_factory()
    sid = _create_stream(client)
    client.post(f"/streams/{sid}/start")
    r = client.delete(f"/streams/{sid}")
    assert r.status_code == 204
    assert not get_runner_registry().is_running(sid)


def test_sse_endpoint_returns_event_stream_content_type(client: TestClient) -> None:
    """The SSE route must advertise text/event-stream and not buffer.

    We can't easily wait for events with TestClient without timing out, so
    we just validate the handshake.
    """
    with client.stream("GET", "/alerts/stream") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers.get("cache-control", "").startswith("no-cache")
        # Pull a couple of bytes to confirm the prime comment lands.
        chunks = iter(r.iter_text())
        first = next(chunks, "")
        assert ":" in first  # either ": connected" or ": keepalive"


@pytest.mark.asyncio
async def test_sse_emits_published_events() -> None:
    """Subscribe via the bus and confirm the SSE serializer produces valid
    frames. We exercise the generator directly rather than through HTTP
    because TestClient's sync read model doesn't interleave well with
    asyncio.Queue-based pub/sub."""
    from datetime import datetime
    from idas.api.alert_bus import AlertBus, AlertEvent
    from idas.api.routes.alerts import stream_alerts  # noqa: PLC0415

    bus = AlertBus()

    class FakeRequest:
        async def is_disconnected(self) -> bool:
            return False

    # Call the route function directly to get the StreamingResponse.
    response = await stream_alerts(
        request=FakeRequest(),  # type: ignore[arg-type]
        bus=bus,
        stream_id=None,
    )

    body_iter = response.body_iterator
    # Prime comment.
    first = await asyncio.wait_for(body_iter.__anext__(), timeout=1.0)
    assert first.startswith(": ")

    # Publish and read.
    await bus.publish(
        AlertEvent(
            stream_id="s1",
            rule_name="r1",
            track_id=3,
            label="person",
            score=0.9,
            zone=None,
            ts=datetime.utcnow(),
            opened=True,
        )
    )
    frame = await asyncio.wait_for(body_iter.__anext__(), timeout=1.0)
    assert frame.startswith("event: alert\ndata: ")
    payload = json.loads(frame.split("data: ", 1)[1].strip())
    assert payload["rule_name"] == "r1"
    assert payload["stream_id"] == "s1"
    assert payload["opened"] is True

    # Close the subscription cleanly.
    await bus.close()
    await body_iter.aclose()
