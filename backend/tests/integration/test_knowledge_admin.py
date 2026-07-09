"""V1.5 knowledge management: admin upload / approve (attach) / remove (detach) /
replace, audited and role-gated. Uses the simulated store (no OpenAI). Provider ids
are never exposed to the client (invariant #6)."""

import httpx

from app.core.config import get_settings
from tests.integration.conftest import Collection

_settings = get_settings()
ADMIN_AUTH = (_settings.admin_username, _settings.admin_password.get_secret_value())
VIEWER_AUTH = (_settings.viewer_username, _settings.viewer_password.get_secret_value())


def _file(name: str = "guide.md", body: bytes = b"# Guide\nHelpful content.") -> dict:
    return {"file": (name, body, "text/markdown")}


async def test_upload_creates_unapproved_source_and_audits(
    client: httpx.AsyncClient, audit_collection: Collection
) -> None:
    resp = await client.post(
        "/api/v1/admin/knowledge-sources",
        files=_file(),
        data={"title": "Portal Guide", "category": "portal", "reason": "new doc"},
        auth=ADMIN_AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Portal Guide" and body["category"] == "portal"
    # Not searchable until approved: unapproved, active, pending index.
    assert body["approved"] is False and body["lifecycle"] == "active"
    assert body["indexing_status"] == "pending"
    assert body["source_id"].startswith("kbs_")
    # Provider ids must NOT be exposed (invariant #6).
    assert "openai_file_id" not in body and "vector_store_id" not in body
    assert await audit_collection.count_documents({"action": "upload_knowledge"}) == 1


async def test_viewer_cannot_upload(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/admin/knowledge-sources",
        files=_file(),
        data={"title": "X", "reason": "r"},
        auth=VIEWER_AUTH,
    )
    assert resp.status_code == 403


async def test_upload_rejects_empty_file(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/admin/knowledge-sources",
        files={"file": ("empty.md", b"", "text/markdown")},
        data={"title": "X", "reason": "r"},
        auth=ADMIN_AUTH,
    )
    assert resp.status_code == 400


async def _upload(client: httpx.AsyncClient, title: str = "Doc") -> str:
    resp = await client.post(
        "/api/v1/admin/knowledge-sources",
        files=_file(),
        data={"title": title, "reason": "seed"},
        auth=ADMIN_AUTH,
    )
    return resp.json()["source_id"]


async def test_content_endpoint_returns_stored_text(client: httpx.AsyncClient) -> None:
    sid = await _upload(client, title="Portal Guide")
    resp = await client.get(f"/api/v1/admin/knowledge-sources/{sid}/content", auth=ADMIN_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["title"] == "Portal Guide"
    assert body["content"] == "# Guide\nHelpful content."
    # The list must NOT leak the (potentially large) content text.
    listing = await client.get("/api/v1/admin/knowledge-sources", auth=ADMIN_AUTH)
    assert all("content" not in s and "content_text" not in s for s in listing.json()["sources"])


async def test_content_endpoint_viewer_can_read(client: httpx.AsyncClient) -> None:
    sid = await _upload(client)
    resp = await client.get(f"/api/v1/admin/knowledge-sources/{sid}/content", auth=VIEWER_AUTH)
    assert resp.status_code == 200 and resp.json()["available"] is True


async def test_content_endpoint_binary_upload_has_no_preview(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/admin/knowledge-sources",
        files={"file": ("logo.bin", b"\xff\xfe\x00\x01binary", "application/octet-stream")},
        data={"title": "Binary", "reason": "r"},
        auth=ADMIN_AUTH,
    )
    sid = resp.json()["source_id"]
    body = (
        await client.get(f"/api/v1/admin/knowledge-sources/{sid}/content", auth=ADMIN_AUTH)
    ).json()
    assert body["available"] is False and body["content"] is None


async def test_content_endpoint_unknown_id_rejected(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/admin/knowledge-sources/kbs_missing/content", auth=ADMIN_AUTH)
    assert resp.status_code == 400


async def test_approve_attaches_and_marks_indexed(
    client: httpx.AsyncClient, audit_collection: Collection
) -> None:
    sid = await _upload(client)
    resp = await client.post(
        f"/api/v1/admin/knowledge-sources/{sid}/approve",
        json={"reason": "reviewed"},
        auth=ADMIN_AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    # Simulated store attaches + reports indexed immediately.
    assert body["approved"] is True and body["indexing_status"] == "indexed"
    assert await audit_collection.count_documents({"action": "approve_knowledge"}) == 1


async def test_remove_detaches_and_marks_removed(
    client: httpx.AsyncClient, audit_collection: Collection
) -> None:
    sid = await _upload(client)
    # Approve first so the source is actually attached — then remove must detach it.
    await client.post(
        f"/api/v1/admin/knowledge-sources/{sid}/approve", json={"reason": "ok"}, auth=ADMIN_AUTH
    )
    resp = await client.post(
        f"/api/v1/admin/knowledge-sources/{sid}/remove",
        json={"reason": "outdated"},
        auth=ADMIN_AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["lifecycle"] == "removed" and body["approved"] is False
    assert await audit_collection.count_documents({"action": "remove_knowledge"}) == 1


async def test_remove_unapproved_source_skips_detach(client: httpx.AsyncClient) -> None:
    # An unapproved source was never attached; remove must NOT call store.detach (which
    # would 404 on the real store). Uses a store that fails loudly if detach is called.
    from app.api.deps import get_knowledge_store
    from app.domain.knowledge.store import SimulatedKnowledgeStore
    from app.main import app

    class _DetachBoomStore(SimulatedKnowledgeStore):
        async def detach(self, file_id: str) -> None:
            raise AssertionError("detach must not be called for an unapproved source")

    app.dependency_overrides[get_knowledge_store] = lambda: _DetachBoomStore()
    try:
        sid = await _upload(client)  # unapproved → never attached
        resp = await client.post(
            f"/api/v1/admin/knowledge-sources/{sid}/remove",
            json={"reason": "never mind"},
            auth=ADMIN_AUTH,
        )
    finally:
        app.dependency_overrides[get_knowledge_store] = SimulatedKnowledgeStore
    assert resp.status_code == 200
    assert resp.json()["lifecycle"] == "removed"


async def test_replace_creates_new_and_retires_old(
    client: httpx.AsyncClient, knowledge_collection: Collection, audit_collection: Collection
) -> None:
    sid = await _upload(client, title="Original")
    resp = await client.post(
        f"/api/v1/admin/knowledge-sources/{sid}/replace",
        files=_file("v2.md", b"# Guide v2"),
        data={"reason": "updated content"},
        auth=ADMIN_AUTH,
    )
    assert resp.status_code == 200
    new = resp.json()
    assert new["source_id"] != sid and new["title"] == "Original"  # inherits title
    assert new["approved"] is False and new["lifecycle"] == "active"  # re-needs approval
    old = await knowledge_collection.find_one({"_id": sid})
    assert old is not None and old["lifecycle"] == "replaced"
    assert await audit_collection.count_documents({"action": "replace_knowledge"}) == 1


async def test_list_shows_sources_without_provider_ids(client: httpx.AsyncClient) -> None:
    await _upload(client, title="Listed")
    resp = await client.get(
        "/api/v1/admin/knowledge-sources", auth=VIEWER_AUTH
    )  # read: either role
    assert resp.status_code == 200
    sources = resp.json()["sources"]
    assert any(s["title"] == "Listed" for s in sources)
    assert all("openai_file_id" not in s and "vector_store_id" not in s for s in sources)


async def test_approve_missing_source_rejected(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/admin/knowledge-sources/kbs_missing/approve",
        json={"reason": "x"},
        auth=ADMIN_AUTH,
    )
    assert resp.status_code == 400


async def test_upload_rejects_oversized_file(client: httpx.AsyncClient) -> None:
    # A file over the per-endpoint cap (5 MB) is rejected with 413 — the read is bounded
    # (read(MAX+1)) so it never materializes the whole body in the handler.
    big = b"x" * (5 * 1024 * 1024 + 1)
    resp = await client.post(
        "/api/v1/admin/knowledge-sources",
        files={"file": ("big.md", big, "text/markdown")},
        data={"title": "Big", "reason": "r"},
        auth=ADMIN_AUTH,
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


async def test_oversized_request_body_rejected_by_middleware(client: httpx.AsyncClient) -> None:
    # A declared body over the global cap (10 MB) is rejected before routing/parsing/auth,
    # so a huge upload can't exhaust the shared process. No auth needed — the guard is
    # upstream of the route.
    resp = await client.post(
        "/api/v1/admin/knowledge-sources", content=b"x" * (10 * 1024 * 1024 + 1)
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


async def test_approve_audits_before_attaching(
    client: httpx.AsyncClient, knowledge_collection: Collection, audit_collection: Collection
) -> None:
    # Approve is the serving gate: it must AUDIT before it attaches, so a store failure
    # never leaves served-but-un-audited content. With a store whose attach fails, the
    # request 500s but the audit is written and the source stays unapproved.
    from app.api.deps import get_knowledge_store
    from app.domain.knowledge.store import (
        IndexingStatus,
        KnowledgeStoreError,
        SimulatedKnowledgeStore,
    )
    from app.main import app

    sid = await _upload(client)

    class _FailingAttachStore:
        channel = "failing"

        async def upload(self, *, filename: str, content: bytes) -> str:
            return "f"

        async def attach(self, file_id: str, *, attributes: dict[str, str]) -> IndexingStatus:
            raise KnowledgeStoreError("attach_failed", retryable=True)

        async def status(self, file_id: str) -> IndexingStatus:
            return "pending"

        async def detach(self, file_id: str) -> None:
            return None

    app.dependency_overrides[get_knowledge_store] = lambda: _FailingAttachStore()
    try:
        resp = await client.post(
            f"/api/v1/admin/knowledge-sources/{sid}/approve",
            json={"reason": "reviewed"},
            auth=ADMIN_AUTH,
        )
    finally:
        app.dependency_overrides[get_knowledge_store] = SimulatedKnowledgeStore
    assert resp.status_code == 500
    # Audited despite the attach failure (audit-before), and NOT left approved/served.
    assert await audit_collection.count_documents({"action": "approve_knowledge"}) == 1
    src = await knowledge_collection.find_one({"_id": sid})
    assert src is not None and src["approved"] is False
