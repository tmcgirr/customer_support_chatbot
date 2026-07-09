import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.core.config import get_settings
from app.domain.ratelimit.repository import RateLimitRepository
from tests.integration.conftest import Collection
from tests.integration.test_chat import _auth, _create, _send_sse

_settings = get_settings()


async def test_hit_allows_up_to_limit_then_blocks(ratelimit_collection: Collection) -> None:
    repo = RateLimitRepository(ratelimit_collection, secret="s")
    now = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)
    results = [await repo.hit("1.2.3.4", limit=3, window_seconds=3600, now=now) for _ in range(4)]
    assert results == [True, True, True, False]


async def test_hit_is_per_identifier(ratelimit_collection: Collection) -> None:
    repo = RateLimitRepository(ratelimit_collection, secret="s")
    now = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)
    assert await repo.hit("a", limit=1, window_seconds=3600, now=now) is True
    assert await repo.hit("a", limit=1, window_seconds=3600, now=now) is False
    # A different IP has its own counter.
    assert await repo.hit("b", limit=1, window_seconds=3600, now=now) is True


async def test_hit_resets_in_next_window(ratelimit_collection: Collection) -> None:
    repo = RateLimitRepository(ratelimit_collection, secret="s")
    now = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)
    assert await repo.hit("a", limit=1, window_seconds=3600, now=now) is True
    assert await repo.hit("a", limit=1, window_seconds=3600, now=now) is False
    later = now + timedelta(seconds=3600)
    assert await repo.hit("a", limit=1, window_seconds=3600, now=later) is True


async def test_create_endpoint_rate_limited(client: httpx.AsyncClient) -> None:
    cap = _settings.ip_create_cap
    for _ in range(cap):
        resp = await client.post("/api/v1/conversations", json={})
        assert resp.status_code == 200
    blocked = await client.post("/api/v1/conversations", json={})
    assert blocked.status_code == 429
    body = blocked.json()
    assert body["error"]["code"] == "RATE_LIMIT"
    assert body["error"]["retryable"] is True


async def test_create_concurrent_is_atomic(client: httpx.AsyncClient) -> None:
    cap = _settings.ip_create_cap
    responses = await asyncio.gather(
        *(client.post("/api/v1/conversations", json={}) for _ in range(cap + 5))
    )
    codes = [r.status_code for r in responses]
    # Exactly `cap` allowed even under concurrent creation — no undercount.
    assert codes.count(200) == cap
    assert codes.count(429) == 5


async def test_message_endpoint_rate_limited(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The paid LLM path is throttled per-session (SECURITY_REVIEW_V1 M1). Two turns are
    # allowed; the third is 429 before a model call is ever made.
    monkeypatch.setattr(_settings, "message_rate_cap", 2)
    cid, token = await _create(client)
    await _send_sse(client, cid, token, "one", "cmid_1")
    await _send_sse(client, cid, token, "two", "cmid_2")
    blocked = await client.post(
        f"/api/v1/conversations/{cid}/messages",
        json={"content": "three", "client_message_id": "cmid_3"},
        headers=_auth(token),
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMIT"


async def test_request_endpoint_rate_limited(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each fresh Idempotency-Key can fire one external delivery; cap submissions per
    # conversation so one session can't flood the team inbox (SECURITY_REVIEW_V1 H1).
    monkeypatch.setattr(_settings, "request_conversation_cap", 2)
    cid, token = await _create(client)
    payload: dict[str, Any] = {
        "type": "strategy_call",
        "conversation_id": cid,
        "contact": {"name": "Ada", "email": "ada@acme.com", "company": "Acme"},
        "fields": {"reason": "Automate invoices."},
        "consent_version": "consent-2026-07",
        "confirmed": True,
    }
    for i in range(2):
        ok = await client.post(
            "/api/v1/requests",
            json=payload,
            headers={**_auth(token), "Idempotency-Key": f"k{i}"},
        )
        assert ok.status_code == 200
    blocked = await client.post(
        "/api/v1/requests", json=payload, headers={**_auth(token), "Idempotency-Key": "k2"}
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMIT"
