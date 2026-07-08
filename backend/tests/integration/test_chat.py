import json
from datetime import UTC, datetime
from typing import Any

import httpx

from app.agent.adapter import AdapterError, TextDelta
from app.core.config import get_settings
from app.core.security import mint_session_token
from app.domain.conversations.repository import ConversationRepository
from tests.fakes import FakeAdapter
from tests.integration.conftest import Collection


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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


async def _create(client: httpx.AsyncClient) -> tuple[str, str]:
    resp = await client.post("/api/v1/conversations", json={"entry_page": "/services"})
    assert resp.status_code == 200
    body = resp.json()
    return body["conversation_id"], body["session_token"]


async def _send_sse(
    client: httpx.AsyncClient, cid: str, token: str, content: str, cmid: str
) -> list[dict[str, Any]]:
    raw = ""
    async with client.stream(
        "POST",
        f"/api/v1/conversations/{cid}/messages",
        json={"content": content, "client_message_id": cmid},
        headers=_auth(token),
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        async for chunk in resp.aiter_text():
            raw += chunk
    return _parse_sse(raw)


async def test_create_conversation(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/conversations", json={"entry_page": "/services"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"].startswith("cnv_")
    assert body["session_token"]
    assert body["welcome"]["text"]
    assert len(body["welcome"]["suggested_actions"]) == 4


async def test_full_chat_stream(client: httpx.AsyncClient, fake_adapter: FakeAdapter) -> None:
    cid, token = await _create(client)
    events = await _send_sse(client, cid, token, "What does Cadre do?", "cmid_1")

    names = [e["event"] for e in events]
    assert names[0] == "message.accepted"
    assert "response.started" in names
    assert names.count("response.delta") >= 1
    assert names[-1] == "response.completed"

    text = "".join(e["data"]["text"] for e in events if e["event"] == "response.delta")
    assert "AI confusion to AI confidence" in text
    assert events[-1]["data"]["assistant_message_id"].startswith("msg_")

    # The adapter received the versioned system prompt + the user turn.
    call = fake_adapter.calls[0]
    assert "Cadre AI Assistant" in call.instructions
    assert call.messages[-1].content == "What does Cadre do?"

    # Transcript persisted: user then assistant, completed.
    transcript = await client.get(f"/api/v1/conversations/{cid}/messages", headers=_auth(token))
    messages = transcript.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["status"] == "completed"
    assert "AI confidence" in messages[1]["content"]


async def test_duplicate_client_message_id_replays(client: httpx.AsyncClient) -> None:
    cid, token = await _create(client)
    await _send_sse(client, cid, token, "First question", "cmid_dup")
    events = await _send_sse(client, cid, token, "First question again", "cmid_dup")

    assert events[-1]["event"] == "response.completed"
    text = "".join(e["data"]["text"] for e in events if e["event"] == "response.delta")
    assert "AI confidence" in text

    transcript = await client.get(f"/api/v1/conversations/{cid}/messages", headers=_auth(token))
    messages = transcript.json()["messages"]
    assert sum(1 for m in messages if m["role"] == "user") == 1


async def test_concurrent_send_returns_busy_409(
    client: httpx.AsyncClient, collection: Collection
) -> None:
    cid, token = await _create(client)
    # Simulate an in-progress run holding the lock.
    await collection.update_one(
        {"_id": cid},
        {"$set": {"active_run": {"run_id": "run_x", "started_at": datetime.now(UTC)}}},
    )
    resp = await client.post(
        f"/api/v1/conversations/{cid}/messages",
        json={"content": "hi", "client_message_id": "cmid_1"},
        headers=_auth(token),
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "CONVERSATION_BUSY"


async def test_cap_reached_streams_limit(client: httpx.AsyncClient, collection: Collection) -> None:
    convo = await ConversationRepository(collection).create(message_cap=0)
    token = mint_session_token(convo.id)
    events = await _send_sse(client, convo.id, token, "hi", "cmid_1")
    assert [e["event"] for e in events] == ["limit.reached"]
    assert "chat limit" in events[0]["data"]["message"]


async def test_adapter_failure_persists_failed_message(
    client: httpx.AsyncClient, fake_adapter: FakeAdapter
) -> None:
    fake_adapter.events = [TextDelta(text="Partial answer ")]
    fake_adapter.raises = AdapterError()

    cid, token = await _create(client)
    events = await _send_sse(client, cid, token, "hi", "cmid_1")

    names = [e["event"] for e in events]
    assert "response.delta" in names
    assert names[-1] == "response.failed"
    assert events[-1]["data"]["error"]["code"] == "MODEL_UNAVAILABLE"

    transcript = await client.get(f"/api/v1/conversations/{cid}/messages", headers=_auth(token))
    assistant = [m for m in transcript.json()["messages"] if m["role"] == "assistant"][0]
    assert assistant["status"] == "failed"
    assert "Partial answer" in assistant["content"]


async def test_message_too_long(client: httpx.AsyncClient) -> None:
    cid, token = await _create(client)
    long_content = "x" * (get_settings().message_max_chars + 1)
    resp = await client.post(
        f"/api/v1/conversations/{cid}/messages",
        json={"content": long_content, "client_message_id": "cmid_1"},
        headers=_auth(token),
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "MESSAGE_TOO_LONG"


async def test_missing_token_is_unauthorized(client: httpx.AsyncClient) -> None:
    cid, _ = await _create(client)
    resp = await client.post(
        f"/api/v1/conversations/{cid}/messages",
        json={"content": "hi", "client_message_id": "cmid_1"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED_SESSION"


async def test_token_for_other_conversation_rejected(client: httpx.AsyncClient) -> None:
    cid, _ = await _create(client)
    _, other_token = await _create(client)
    resp = await client.post(
        f"/api/v1/conversations/{cid}/messages",
        json={"content": "hi", "client_message_id": "cmid_1"},
        headers=_auth(other_token),
    )
    assert resp.status_code == 401
