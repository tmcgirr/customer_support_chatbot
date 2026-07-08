import json
from typing import Any

import httpx
import pytest


def _parse_sse(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in raw.strip().split("\n\n"):
        if not block.strip():
            continue
        event: dict[str, Any] = {}
        for line in block.splitlines():
            if line.startswith("event:"):
                event["event"] = line[len("event:") :].strip()
            elif line.startswith("data:"):
                event["data"] = json.loads(line[len("data:") :].strip())
        events.append(event)
    return events


async def test_stream_test_event_sequence(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Keep the test fast; the 0.3s cadence only matters for the browser demo.
    monkeypatch.setattr("app.api.dev._DELTA_INTERVAL_SECONDS", 0.0)

    raw = ""
    async with client.stream("GET", "/api/v1/dev/stream-test") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["X-Accel-Buffering"] == "no"
        async for chunk in resp.aiter_text():
            raw += chunk

    events = _parse_sse(raw)
    names = [e["event"] for e in events]

    assert names[0] == "response.started"
    assert names[-1] == "response.completed"
    assert names.count("response.delta") == 10

    deltas = [e for e in events if e["event"] == "response.delta"]
    assert [d["data"]["index"] for d in deltas] == list(range(10))
    assert "".join(d["data"]["text"] for d in deltas).startswith("Cadre AI")
