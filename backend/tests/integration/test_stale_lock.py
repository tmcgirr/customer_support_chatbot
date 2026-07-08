from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import get_settings
from app.domain.conversations.models import Message
from app.domain.conversations.repository import ConversationRepository
from tests.integration.conftest import Collection
from tests.integration.test_chat import _auth, _create, _parse_sse, _send_sse

_settings = get_settings()


def _lock(age_seconds: int) -> dict[str, object]:
    return {
        "run_id": "run_leaked",
        "started_at": datetime.now(UTC) - timedelta(seconds=age_seconds),
    }


async def test_stale_lock_recovered_on_send(
    client: httpx.AsyncClient, collection: Collection
) -> None:
    cid, token = await _create(client)
    # Simulate a turn that crashed after acquiring the lock long ago.
    await collection.update_one(
        {"_id": cid}, {"$set": {"active_run": _lock(_settings.lock_stale_seconds + 60)}}
    )

    events = await _send_sse(client, cid, token, "What does Cadre do?", "cmid_1")
    names = [e["event"] for e in events]
    assert "response.completed" in names  # recovered and completed a fresh turn

    doc = await collection.find_one({"_id": cid})
    assert doc is not None and doc["active_run"] is None


async def test_fresh_lock_stays_busy(client: httpx.AsyncClient, collection: Collection) -> None:
    cid, token = await _create(client)
    # A genuinely in-flight turn (young lock) must NOT be recovered.
    await collection.update_one({"_id": cid}, {"$set": {"active_run": _lock(5)}})

    resp = await client.post(
        f"/api/v1/conversations/{cid}/messages",
        json={"content": "hello", "client_message_id": "cmid_1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "CONVERSATION_BUSY"


async def test_touch_lock_protects_a_live_slow_turn(
    client: httpx.AsyncClient, collection: Collection
) -> None:
    # A live turn heartbeats its lock; even if it started long ago, the refresh
    # keeps it young so the stale sweep never reclaims it.
    cid, _ = await _create(client)
    repo = ConversationRepository(collection)
    await collection.update_one(
        {"_id": cid}, {"$set": {"active_run": _lock(_settings.lock_stale_seconds + 300)}}
    )

    await repo.touch_lock(cid, "run_leaked")  # heartbeat

    cutoff = datetime.now(UTC) - timedelta(seconds=_settings.lock_stale_seconds)
    assert await repo.clear_stale_lock(cid, cutoff) is False  # refreshed → not stale
    doc = await collection.find_one({"_id": cid})
    assert doc is not None and doc["active_run"] is not None


async def test_crashed_same_cmid_replay_surfaces_failure(
    client: httpx.AsyncClient, collection: Collection
) -> None:
    # Original turn crashed: its user message is stored (cmid), lock leaked, no
    # assistant reply. A resend with the SAME cmid must NOT emit a blank success.
    cid, token = await _create(client)
    crashed = Message(
        id="msg_crashed",
        role="user",
        content="What does Cadre do?",
        client_message_id="cmid_dupe",
        status="completed",
        created_at=datetime.now(UTC),
    )
    await collection.update_one(
        {"_id": cid},
        {
            "$push": {"messages": crashed.model_dump()},
            "$set": {"active_run": _lock(_settings.lock_stale_seconds + 60), "message_count": 1},
        },
    )

    raw = ""
    async with client.stream(
        "POST",
        f"/api/v1/conversations/{cid}/messages",
        json={"content": "What does Cadre do?", "client_message_id": "cmid_dupe"},
        headers=_auth(token),
    ) as resp:
        assert resp.status_code == 200
        async for chunk in resp.aiter_text():
            raw += chunk
    names = [e["event"] for e in _parse_sse(raw)]
    assert "response.failed" in names
    assert "response.completed" not in names
