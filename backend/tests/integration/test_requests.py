from typing import Any

import httpx

from tests.integration.conftest import Collection
from tests.integration.test_chat import _auth, _create, _send_sse


def _strategy_payload(conversation_id: str) -> dict[str, Any]:
    return {
        "type": "strategy_call",
        "conversation_id": conversation_id,
        "contact": {"name": "Ada Smith", "email": "ada@acme.com", "company": "Acme"},
        "fields": {"reason": "We want to automate invoice processing."},
        "consent_version": "consent-2026-07",
        "confirmed": True,
    }


async def _submit(
    client: httpx.AsyncClient, token: str, payload: dict[str, Any], key: str = "idem-1"
) -> httpx.Response:
    return await client.post(
        "/api/v1/requests", json=payload, headers={**_auth(token), "Idempotency-Key": key}
    )


async def test_strategy_call_success_records_outcome(
    client: httpx.AsyncClient, collection: Collection
) -> None:
    cid, token = await _create(client)
    resp = await _submit(client, token, _strategy_payload(cid))

    assert resp.status_code == 200
    body = resp.json()
    assert body["request_id"].startswith("req_")
    assert body["reference"].startswith("REQ-")
    assert body["status"] == "received"
    assert body["duplicate"] is False

    doc = await collection.find_one({"_id": cid})
    assert doc is not None
    assert doc["outcome"] == "strategy_call_requested"


async def test_idempotent_replay(
    client: httpx.AsyncClient, requests_collection: Collection
) -> None:
    cid, token = await _create(client)
    first = await _submit(client, token, _strategy_payload(cid), key="idem-x")
    second = await _submit(client, token, _strategy_payload(cid), key="idem-x")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["request_id"] == first.json()["request_id"]
    assert second.json()["reference"] == first.json()["reference"]
    assert await requests_collection.count_documents({}) == 1


async def test_portal_support_success(client: httpx.AsyncClient) -> None:
    cid, token = await _create(client)
    payload = {
        "type": "portal_support",
        "conversation_id": cid,
        "contact": {"name": "A", "email": "a@b.com", "company": "C"},
        "fields": {"issue_category": "forgot_password", "description": "Can't sign in."},
        "consent_version": "consent-2026-07",
        "confirmed": True,
    }
    assert (await _submit(client, token, payload)).status_code == 200


async def test_human_escalation_allows_empty_contact(client: httpx.AsyncClient) -> None:
    cid, token = await _create(client)
    payload = {
        "type": "human_escalation",
        "conversation_id": cid,
        "contact": {},
        "fields": {
            "category": "other",
            "original_question": "How do you handle data residency?",
            "context_summary": "Asked about EU residency.",
        },
        "consent_version": "consent-2026-07",
        "confirmed": True,
    }
    resp = await _submit(client, token, payload)
    assert resp.status_code == 200
    assert resp.json()["duplicate"] is False


async def test_invalid_email_rejected(client: httpx.AsyncClient) -> None:
    cid, token = await _create(client)
    payload = _strategy_payload(cid)
    payload["contact"]["email"] = "not-an-email"
    resp = await _submit(client, token, payload)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_EMAIL"


async def test_missing_required_field_rejected(client: httpx.AsyncClient) -> None:
    cid, token = await _create(client)
    payload = _strategy_payload(cid)
    payload["fields"] = {}
    resp = await _submit(client, token, payload)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_REQUEST"


async def test_not_confirmed_rejected(client: httpx.AsyncClient) -> None:
    cid, token = await _create(client)
    payload = _strategy_payload(cid)
    payload["confirmed"] = False
    assert (await _submit(client, token, payload)).status_code == 400


async def test_missing_idempotency_key_rejected(client: httpx.AsyncClient) -> None:
    cid, token = await _create(client)
    resp = await client.post("/api/v1/requests", json=_strategy_payload(cid), headers=_auth(token))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_REQUEST"


async def test_token_for_other_conversation_rejected(client: httpx.AsyncClient) -> None:
    cid, _ = await _create(client)
    _, other_token = await _create(client)
    resp = await _submit(client, other_token, _strategy_payload(cid))
    assert resp.status_code == 401


async def test_feedback_ownership(client: httpx.AsyncClient) -> None:
    cid, token = await _create(client)
    events = await _send_sse(client, cid, token, "What do you do?", "cmid_1")
    assistant_id = events[-1]["data"]["assistant_message_id"]

    ok = await client.post(
        f"/api/v1/messages/{assistant_id}/feedback",
        json={"rating": "helpful"},
        headers=_auth(token),
    )
    assert ok.status_code == 200

    # A message that isn't in this conversation is rejected.
    bad = await client.post(
        "/api/v1/messages/msg_not_in_convo/feedback",
        json={"rating": "not_helpful", "reason": "unclear"},
        headers=_auth(token),
    )
    assert bad.status_code == 400


async def test_feedback_requires_token(client: httpx.AsyncClient) -> None:
    await _create(client)
    resp = await client.post("/api/v1/messages/msg_x/feedback", json={"rating": "helpful"})
    assert resp.status_code == 401


async def test_idempotency_is_per_conversation(
    client: httpx.AsyncClient, requests_collection: Collection
) -> None:
    cid_a, token_a = await _create(client)
    cid_b, token_b = await _create(client)
    a = await _submit(client, token_a, _strategy_payload(cid_a), key="shared")
    b = await _submit(client, token_b, _strategy_payload(cid_b), key="shared")

    assert a.json()["duplicate"] is False
    assert b.json()["duplicate"] is False  # same key, different conversation -> not a replay
    assert a.json()["request_id"] != b.json()["request_id"]
    assert await requests_collection.count_documents({}) == 2


async def test_replay_returns_original_even_if_new_payload_invalid(
    client: httpx.AsyncClient,
) -> None:
    cid, token = await _create(client)
    first = await _submit(client, token, _strategy_payload(cid), key="k2")
    assert first.status_code == 200

    invalid = _strategy_payload(cid)
    invalid["fields"] = {}  # would fail validation on a fresh submit
    replay = await _submit(client, token, invalid, key="k2")
    assert replay.status_code == 200
    assert replay.json()["duplicate"] is True
    assert replay.json()["reference"] == first.json()["reference"]


async def test_oversize_field_rejected(client: httpx.AsyncClient) -> None:
    cid, token = await _create(client)
    payload = _strategy_payload(cid)
    payload["fields"]["reason"] = "x" * 5000
    resp = await _submit(client, token, payload)
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "MESSAGE_TOO_LONG"


async def test_feedback_deduped_per_message(
    client: httpx.AsyncClient, feedback_collection: Collection
) -> None:
    cid, token = await _create(client)
    events = await _send_sse(client, cid, token, "Hi", "cmid_1")
    assistant_id = events[-1]["data"]["assistant_message_id"]

    for rating in ("helpful", "not_helpful"):
        resp = await client.post(
            f"/api/v1/messages/{assistant_id}/feedback",
            json={"rating": rating},
            headers=_auth(token),
        )
        assert resp.status_code == 200

    assert await feedback_collection.count_documents({}) == 1  # one row per message
    doc = await feedback_collection.find_one({"message_id": assistant_id})
    assert doc is not None
    assert doc["rating"] == "not_helpful"  # last write wins
