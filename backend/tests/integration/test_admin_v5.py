"""Admin V1: roles (admin/viewer), audited privileged actions (reveal, redeliver,
approve). The checkpoint lives here."""

from datetime import UTC, datetime

import httpx

from app.core import ids
from app.core.config import get_settings
from app.domain.canonical.models import CanonicalAnswer
from app.domain.requests.models import Contact, RequestRecord
from tests.integration.conftest import Collection

_settings = get_settings()
ADMIN_AUTH = (_settings.admin_username, _settings.admin_password.get_secret_value())
VIEWER_AUTH = (_settings.viewer_username, _settings.viewer_password.get_secret_value())


async def _insert_request(
    requests_collection: Collection, *, status: str = "received", email: str = "ada@acme.com"
) -> str:
    record = RequestRecord(
        id=ids.request_id(),
        type="strategy_call",
        conversation_id="cnv_admin",
        idempotency_key=ids.prefixed_id("key"),
        reference="REF-ADMIN",
        contact=Contact(name="Ada Lovelace", email=email),
        fields={"reason": "exploring AI"},
        consent_version="c",
        status=status,  # type: ignore[arg-type]
        created_at=datetime.now(UTC),
    )
    await requests_collection.insert_one(record.model_dump(by_alias=True))
    return record.id


# --- Roles ---


async def test_viewer_can_read_dashboard(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/admin/dashboard", auth=VIEWER_AUTH)
    assert resp.status_code == 200


async def test_viewer_denied_reveal(
    client: httpx.AsyncClient, requests_collection: Collection
) -> None:
    rid = await _insert_request(requests_collection)
    resp = await client.post(
        f"/api/v1/admin/requests/{rid}/reveal", json={"reason": "support"}, auth=VIEWER_AUTH
    )
    assert resp.status_code == 403  # authenticated but insufficient role


async def test_viewer_denied_redeliver_and_approve(client: httpx.AsyncClient) -> None:
    r1 = await client.post(
        "/api/v1/admin/requests/req_x/redeliver", json={"reason": "x"}, auth=VIEWER_AUTH
    )
    r2 = await client.post(
        "/api/v1/admin/canonical/pricing/approve", json={"reason": "x"}, auth=VIEWER_AUTH
    )
    assert r1.status_code == 403 and r2.status_code == 403


async def test_bad_credentials_still_401(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/admin/dashboard", auth=("viewer", "wrong"))
    assert resp.status_code == 401


# --- Reveal (admin, reason required, audited) ---


async def test_admin_reveal_returns_unmasked_and_audits(
    client: httpx.AsyncClient, requests_collection: Collection, audit_collection: Collection
) -> None:
    rid = await _insert_request(requests_collection, email="ada@acme.com")
    resp = await client.post(
        f"/api/v1/admin/requests/{rid}/reveal", json={"reason": "verify contact"}, auth=ADMIN_AUTH
    )
    assert resp.status_code == 200
    assert resp.json()["contact"]["email"] == "ada@acme.com"  # unmasked

    audits = await audit_collection.find({"action": "reveal_request"}).to_list(length=None)
    assert len(audits) == 1
    assert audits[0]["target_id"] == rid and audits[0]["reason"] == "verify contact"
    assert audits[0]["actor"] == _settings.admin_username


async def test_reveal_requires_a_reason(
    client: httpx.AsyncClient, requests_collection: Collection
) -> None:
    rid = await _insert_request(requests_collection)
    resp = await client.post(
        f"/api/v1/admin/requests/{rid}/reveal", json={"reason": ""}, auth=ADMIN_AUTH
    )
    # The app maps request-body validation errors to 400 INVALID_REQUEST (contracts §6).
    assert resp.status_code == 400


async def test_audit_reason_pii_is_masked(
    client: httpx.AsyncClient, requests_collection: Collection, audit_collection: Collection
) -> None:
    # The reason is operator free-text; any email/phone in it must be masked so no
    # PII lands in the audit trail at rest or via GET /audit (invariant #5).
    rid = await _insert_request(requests_collection)
    await client.post(
        f"/api/v1/admin/requests/{rid}/reveal",
        json={"reason": "called ada@acme.com to confirm"},
        auth=ADMIN_AUTH,
    )
    doc = await audit_collection.find_one({"action": "reveal_request"})
    assert doc is not None
    assert "ada@acme.com" not in doc["reason"] and "a***@acme.com" in doc["reason"]


async def test_reveal_conversation_unmasked_and_audited(
    client: httpx.AsyncClient, collection: Collection, audit_collection: Collection
) -> None:
    from tests.integration.test_chat import _create, _send_sse

    cid, token = await _create(client)
    await _send_sse(client, cid, token, "Reach me at ada@acme.com", "cmid_1")
    resp = await client.post(
        f"/api/v1/admin/conversations/{cid}/reveal", json={"reason": "audit"}, auth=ADMIN_AUTH
    )
    assert resp.status_code == 200
    joined = " ".join(m["content"] for m in resp.json()["messages"])
    assert "ada@acme.com" in joined  # unmasked here (masked on the normal detail view)
    assert await audit_collection.count_documents({"action": "reveal_conversation"}) == 1


# --- Redeliver (admin, audited) ---


async def test_redeliver_resets_and_reenqueues_and_audits(
    client: httpx.AsyncClient,
    requests_collection: Collection,
    jobs_collection: Collection,
    audit_collection: Collection,
) -> None:
    rid = await _insert_request(requests_collection, status="delivery_failed")
    resp = await client.post(
        f"/api/v1/admin/requests/{rid}/redeliver", json={"reason": "retry"}, auth=ADMIN_AUTH
    )
    assert resp.status_code == 200
    doc = await requests_collection.find_one({"_id": rid})
    assert doc is not None and doc["status"] == "received"  # reset for redelivery
    jobs = await jobs_collection.find({"type": "deliver_request", "resource_id": rid}).to_list(
        length=None
    )
    assert len(jobs) == 1  # a fresh delivery job enqueued
    assert await audit_collection.count_documents({"action": "redeliver_request"}) == 1


async def test_redeliver_nonfailed_request_rejected(
    client: httpx.AsyncClient,
    requests_collection: Collection,
    jobs_collection: Collection,
    audit_collection: Collection,
) -> None:
    rid = await _insert_request(requests_collection, status="received")
    resp = await client.post(
        f"/api/v1/admin/requests/{rid}/redeliver", json={"reason": "x"}, auth=ADMIN_AUTH
    )
    assert resp.status_code == 400  # only delivery_failed can be redelivered
    # An invalid action must NOT audit or enqueue (validate-before-audit/side-effect).
    assert await audit_collection.count_documents({"action": "redeliver_request"}) == 0
    assert await jobs_collection.count_documents({"resource_id": rid}) == 0


# --- Approve canonical (admin, audited) ---


async def test_approve_publishes_draft_and_audits(
    client: httpx.AsyncClient, canonical_collection: Collection, audit_collection: Collection
) -> None:
    now = datetime.now(UTC)
    await canonical_collection.insert_one(
        CanonicalAnswer(
            id="can_draft",
            name="Draft pricing",
            intent="pricing",
            content="draft wording",
            status="draft",
            owner="Sales",
            effective_date=now,
            review_date=now,
        ).model_dump(by_alias=True)
    )
    resp = await client.post(
        "/api/v1/admin/canonical/pricing/approve", json={"reason": "reviewed"}, auth=ADMIN_AUTH
    )
    assert resp.status_code == 200
    doc = await canonical_collection.find_one({"intent": "pricing"})
    assert doc is not None and doc["status"] == "approved"  # now served
    assert await audit_collection.count_documents({"action": "approve_canonical"}) == 1


async def test_approve_missing_draft_rejected(
    client: httpx.AsyncClient, audit_collection: Collection
) -> None:
    resp = await client.post(
        "/api/v1/admin/canonical/no_such_intent/approve", json={"reason": "x"}, auth=ADMIN_AUTH
    )
    assert resp.status_code == 400
    assert await audit_collection.count_documents({"action": "approve_canonical"}) == 0


async def test_monitoring_reports_operational_counts(
    client: httpx.AsyncClient, requests_collection: Collection, jobs_collection: Collection
) -> None:
    # A parked delivery + a dead-lettered job should surface as alert counters.
    await _insert_request(requests_collection, status="delivery_failed")
    await jobs_collection.insert_one(
        {
            "_id": "job_dl",
            "type": "deliver_request",
            "resource_id": "req_x",
            "status": "dead_letter",
            "attempts": 5,
            "max_attempts": 5,
            "available_at": datetime.now(UTC),
            "created_at": datetime.now(UTC),
        }
    )
    resp = await client.get("/api/v1/admin/monitoring", auth=ADMIN_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["delivery_failed"] == 1
    assert body["dead_letter"] == 1
    assert "queue_depth" in body and "privacy_by_status" in body
    # Both critical conditions surface as firing alerts.
    fired = {a["name"]: a for a in body["alerts"]}
    assert set(fired) == {"dead_letter_jobs", "delivery_failed_requests"}
    assert all(a["severity"] == "critical" for a in fired.values())


async def test_monitoring_no_alerts_when_healthy(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/admin/monitoring", auth=ADMIN_AUTH)
    assert resp.status_code == 200
    assert resp.json()["alerts"] == []  # clean baseline


async def test_monitoring_readable_by_viewer(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/admin/monitoring", auth=VIEWER_AUTH)
    assert resp.status_code == 200  # read-only signal, either role


async def test_audit_list_shows_actions(
    client: httpx.AsyncClient, requests_collection: Collection
) -> None:
    rid = await _insert_request(requests_collection)
    await client.post(
        f"/api/v1/admin/requests/{rid}/reveal", json={"reason": "check"}, auth=ADMIN_AUTH
    )
    resp = await client.get("/api/v1/admin/audit", auth=ADMIN_AUTH)
    assert resp.status_code == 200
    entries = resp.json()["entries"]
    assert any(e["action"] == "reveal_request" and e["reason"] == "check" for e in entries)
