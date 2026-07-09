from datetime import UTC, datetime

import httpx
import pytest

from app.agent.adapter import Completed, TextDelta, ToolCall
from app.core.config import get_settings
from tests.fakes import FakeAdapter
from tests.integration.conftest import Collection
from tests.integration.test_chat import _create, _send_sse
from tests.integration.test_requests import _strategy_payload, _submit

_settings = get_settings()
ADMIN_AUTH = (_settings.admin_username, _settings.admin_password.get_secret_value())

ADMIN_ROUTES = [
    "/api/v1/admin/system",
    "/api/v1/admin/dashboard",
    "/api/v1/admin/dashboard/trends",
    "/api/v1/admin/conversations",
    "/api/v1/admin/conversations/cnv_x",
    "/api/v1/admin/requests",
    "/api/v1/admin/unresolved-questions",
]


async def test_system_reports_env_behind_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/admin/system", auth=ADMIN_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["env"] == "dev"
    assert "delivery" in body["feature_flags"]
    assert body["version"]


@pytest.mark.parametrize("route", ADMIN_ROUTES)
async def test_every_admin_route_requires_auth(client: httpx.AsyncClient, route: str) -> None:
    resp = await client.get(route)
    assert resp.status_code == 401
    assert "Basic" in resp.headers.get("WWW-Authenticate", "")


async def test_bad_credentials_rejected(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/admin/dashboard", auth=("admin", "wrong-password"))
    assert resp.status_code == 401


async def test_dashboard_counts(client: httpx.AsyncClient) -> None:
    cid, token = await _create(client)
    await _submit(client, token, _strategy_payload(cid))

    resp = await client.get("/api/v1/admin/dashboard", auth=ADMIN_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversations"]["total"] >= 1
    assert body["requests"]["total"] >= 1
    assert body["requests"]["by_type"].get("strategy_call", 0) >= 1
    # V1.5 analytics buckets are present (unlabeled conversations count as "unset").
    assert "by_topic" in body["conversations"] and "by_intent" in body["conversations"]


async def test_dashboard_trends_shape(client: httpx.AsyncClient) -> None:
    # No daily_aggregates job runs in tests, so the series is empty — but the
    # endpoint must still return the documented shape (a `points` list) behind auth.
    resp = await client.get("/api/v1/admin/dashboard/trends", auth=ADMIN_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"points": []}

    # The window is bounded (1..90 days); an out-of-range value is rejected via the
    # app's validation envelope (400, not FastAPI's default 422).
    resp = await client.get("/api/v1/admin/dashboard/trends?days=0", auth=ADMIN_AUTH)
    assert resp.status_code == 400


async def test_conversation_list_and_detail_expose_summary(
    client: httpx.AsyncClient, collection: Collection
) -> None:
    now = datetime.now(UTC)
    await collection.insert_one(
        {
            "_id": "cnv_sum",
            "status": "completed",
            "message_count": 2,
            "summary": {
                # PII the model echoed from the transcript — must be MASKED by default.
                "tldr": "Asked about pricing; email ada@acme.com.",
                "key_points": ["pricing", "follow up ada@acme.com"],
                "summarized_at": now,
            },
            "messages": [
                {
                    "id": "m",
                    "role": "user",
                    "content": "pricing?",
                    "status": "completed",
                    "created_at": now,
                }
            ],
            "started_at": now,
            "last_activity_at": now,
        }
    )
    listed = await client.get("/api/v1/admin/conversations", auth=ADMIN_AUTH)
    item = next(c for c in listed.json()["conversations"] if c["conversation_id"] == "cnv_sum")
    assert "ada@acme.com" not in item["summary"] and "a***@acme.com" in item["summary"]

    detail = await client.get("/api/v1/admin/conversations/cnv_sum", auth=ADMIN_AUTH)
    body = detail.json()
    assert "ada@acme.com" not in body["summary"] and "a***@acme.com" in body["summary"]
    assert all("ada@acme.com" not in p for p in body["key_points"])
    assert any("a***@acme.com" in p for p in body["key_points"])


async def test_conversation_detail_shows_trace_metadata(
    client: httpx.AsyncClient, fake_adapter: FakeAdapter
) -> None:
    fake_adapter.set_rounds(
        [[TextDelta(text="Hello there"), Completed(usage=None, model="fake-model")]]
    )
    cid, token = await _create(client)
    await _send_sse(client, cid, token, "hi", "cmid_trace")

    resp = await client.get(f"/api/v1/admin/conversations/{cid}", auth=ADMIN_AUTH)
    assistant = [m for m in resp.json()["messages"] if m["role"] == "assistant"][-1]
    assert assistant["prompt_version"] == "sys-v1"
    assert assistant["model"] == "fake-model"
    assert assistant["trace_id"].startswith("trace_")


async def test_conversation_detail_masks_email(client: httpx.AsyncClient) -> None:
    cid, token = await _create(client)
    await _send_sse(client, cid, token, "Reach me at ada@acme.com please", "cmid_1")

    resp = await client.get(f"/api/v1/admin/conversations/{cid}", auth=ADMIN_AUTH)
    assert resp.status_code == 200
    contents = " ".join(m["content"] for m in resp.json()["messages"])
    assert "ada@acme.com" not in contents
    assert "a***@acme.com" in contents


async def test_requests_list_masks_email(client: httpx.AsyncClient) -> None:
    cid, token = await _create(client)
    await _submit(client, token, _strategy_payload(cid))

    resp = await client.get("/api/v1/admin/requests", auth=ADMIN_AUTH)
    records = resp.json()["requests"]
    assert records
    assert all("ada@acme.com" not in r["contact_email"] for r in records)
    assert any(r["contact_email"] == "a***@acme.com" for r in records)


async def test_requests_filter_by_type(client: httpx.AsyncClient) -> None:
    cid, token = await _create(client)
    await _submit(client, token, _strategy_payload(cid), key="k1")
    portal = {
        "type": "portal_support",
        "conversation_id": cid,
        "contact": {"email": "a@b.com"},
        "fields": {"issue_category": "other", "description": "x"},
        "consent_version": "consent-2026-07",
        "confirmed": True,
    }
    await _submit(client, token, portal, key="k2")

    resp = await client.get("/api/v1/admin/requests?type=strategy_call", auth=ADMIN_AUTH)
    assert {r["type"] for r in resp.json()["requests"]} == {"strategy_call"}


async def test_unresolved_populates_after_unsupported(
    client: httpx.AsyncClient, fake_adapter: FakeAdapter
) -> None:
    fake_adapter.set_rounds(
        [
            [
                ToolCall(
                    call_id="c1", name="get_canonical_answer", arguments={"intent": "unsupported"}
                ),
                Completed(usage=None),
            ],
            [TextDelta(text="I don't have approved information for that."), Completed(usage=None)],
        ]
    )
    cid, token = await _create(client)
    await _send_sse(client, cid, token, "What is the meaning of life?", "cmid_1")

    resp = await client.get("/api/v1/admin/unresolved-questions", auth=ADMIN_AUTH)
    assert resp.status_code == 200
    questions = resp.json()["questions"]
    assert any(
        q["question"] == "What is the meaning of life?" and q["conversation_id"] == cid
        for q in questions
    )


async def test_unresolved_questions_mask_pii(
    client: httpx.AsyncClient, fake_adapter: FakeAdapter
) -> None:
    fake_adapter.set_rounds(
        [
            [
                ToolCall(
                    call_id="c1", name="get_canonical_answer", arguments={"intent": "unsupported"}
                ),
                Completed(usage=None),
            ],
            [TextDelta(text="I don't have approved information for that."), Completed(usage=None)],
        ]
    )
    cid, token = await _create(client)
    await _send_sse(client, cid, token, "Delete me, ada@acme.com, 415-555-0142", "cmid_1")

    resp = await client.get("/api/v1/admin/unresolved-questions", auth=ADMIN_AUTH)
    joined = " ".join(q["question"] for q in resp.json()["questions"])
    assert "ada@acme.com" not in joined
    assert "415-555-0142" not in joined
    assert "a***@acme.com" in joined
