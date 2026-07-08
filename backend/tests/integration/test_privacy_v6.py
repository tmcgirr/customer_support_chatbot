"""V6 privacy API: the public request endpoint (no existence leak, rate-limited)
and the audited admin verify (which enqueues the erasure worker job)."""

import httpx

from app.core.config import get_settings
from tests.integration.conftest import Collection

_settings = get_settings()
ADMIN_AUTH = (_settings.admin_username, _settings.admin_password.get_secret_value())
VIEWER_AUTH = (_settings.viewer_username, _settings.viewer_password.get_secret_value())

_ACK_PREFIX = "Your request has been received."


# --- Public endpoint ---


async def test_privacy_request_returns_generic_ack_regardless_of_data(
    client: httpx.AsyncClient, privacy_collection: Collection
) -> None:
    # No session/auth needed. The response is identical whether or not we hold data,
    # so it can't be used to probe existence.
    r1 = await client.post(
        "/api/v1/privacy/requests", json={"type": "deletion", "email": "someone@nowhere.test"}
    )
    r2 = await client.post(
        "/api/v1/privacy/requests",
        json={"type": "access", "email": "ada@acme.com", "conversation_id": "cnv_x"},
    )
    assert r1.status_code == 200 and r2.status_code == 200
    for r in (r1, r2):
        body = r.json()
        assert body["status"] == "received"
        assert body["message"].startswith(_ACK_PREFIX)
        assert body["request_id"].startswith("pvr_")
    # Both were recorded as pending.
    assert await privacy_collection.count_documents({"verification_status": "pending"}) == 2


async def test_privacy_request_invalid_email_rejected(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/privacy/requests", json={"type": "deletion", "email": "not-an-email"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_EMAIL"


async def test_privacy_request_rate_limited_per_ip(client: httpx.AsyncClient) -> None:
    cap = _settings.privacy_request_ip_cap
    last = None
    for _ in range(cap + 1):
        last = await client.post(
            "/api/v1/privacy/requests", json={"type": "deletion", "email": "x@y.com"}
        )
    assert last is not None and last.status_code == 429
    assert last.json()["error"]["code"] == "RATE_LIMIT"


# --- Admin verify (audited, enqueues the erasure) ---


async def _create_request(client: httpx.AsyncClient, *, req_type: str, email: str) -> str:
    resp = await client.post("/api/v1/privacy/requests", json={"type": req_type, "email": email})
    return resp.json()["request_id"]


async def test_viewer_denied_verify(
    client: httpx.AsyncClient, privacy_collection: Collection
) -> None:
    pvr_id = await _create_request(client, req_type="deletion", email="t@x.com")
    resp = await client.post(
        f"/api/v1/admin/privacy-requests/{pvr_id}/verify",
        json={"reason": "id ok"},
        auth=VIEWER_AUTH,
    )
    assert resp.status_code == 403


async def test_admin_verify_deletion_audits_and_enqueues(
    client: httpx.AsyncClient,
    privacy_collection: Collection,
    jobs_collection: Collection,
    audit_collection: Collection,
) -> None:
    pvr_id = await _create_request(client, req_type="deletion", email="t@x.com")
    resp = await client.post(
        f"/api/v1/admin/privacy-requests/{pvr_id}/verify",
        json={"reason": "identity confirmed"},
        auth=ADMIN_AUTH,
    )
    assert resp.status_code == 200
    doc = await privacy_collection.find_one({"_id": pvr_id})
    assert doc is not None and doc["verification_status"] == "verified"
    assert doc["verified_by"] == _settings.admin_username
    # A privacy_delete job was enqueued for the worker; the endpoint never deletes inline.
    assert (
        await jobs_collection.count_documents({"type": "privacy_delete", "resource_id": pvr_id})
        == 1
    )
    assert (
        await audit_collection.count_documents(
            {"action": "verify_privacy_request", "target_id": pvr_id}
        )
        == 1
    )


async def test_admin_verify_access_does_not_enqueue_deletion(
    client: httpx.AsyncClient, privacy_collection: Collection, jobs_collection: Collection
) -> None:
    pvr_id = await _create_request(client, req_type="access", email="t@x.com")
    resp = await client.post(
        f"/api/v1/admin/privacy-requests/{pvr_id}/verify", json={"reason": "ok"}, auth=ADMIN_AUTH
    )
    assert resp.status_code == 200
    assert await jobs_collection.count_documents({"type": "privacy_delete"}) == 0


async def test_verify_nonpending_rejected_without_side_effects(
    client: httpx.AsyncClient, jobs_collection: Collection, audit_collection: Collection
) -> None:
    pvr_id = await _create_request(client, req_type="deletion", email="t@x.com")
    first = await client.post(
        f"/api/v1/admin/privacy-requests/{pvr_id}/verify", json={"reason": "ok"}, auth=ADMIN_AUTH
    )
    assert first.status_code == 200
    # Second verify: already verified → 400, no extra audit, no extra job.
    second = await client.post(
        f"/api/v1/admin/privacy-requests/{pvr_id}/verify", json={"reason": "again"}, auth=ADMIN_AUTH
    )
    assert second.status_code == 400
    assert await audit_collection.count_documents({"target_id": pvr_id}) == 1
    assert await jobs_collection.count_documents({"resource_id": pvr_id}) == 1


async def test_admin_list_privacy_masks_email(
    client: httpx.AsyncClient, privacy_collection: Collection
) -> None:
    await _create_request(client, req_type="deletion", email="ada@acme.com")
    resp = await client.get("/api/v1/admin/privacy-requests", auth=ADMIN_AUTH)
    assert resp.status_code == 200
    entries = resp.json()["requests"]
    assert entries and entries[0]["requester_email"] == "a***@acme.com"
