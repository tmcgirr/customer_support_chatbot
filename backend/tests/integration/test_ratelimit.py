import asyncio
from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import get_settings
from app.domain.ratelimit.repository import RateLimitRepository
from tests.integration.conftest import Collection

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
