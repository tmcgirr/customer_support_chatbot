"""Admin insights endpoints: read latest/list/by-id (either role), and the admin-only,
audited manual Run-now trigger."""

from datetime import UTC, datetime

import httpx

from app.core.config import get_settings
from tests.integration.conftest import Collection

_settings = get_settings()
ADMIN_AUTH = (_settings.admin_username, _settings.admin_password.get_secret_value())
VIEWER_AUTH = (_settings.viewer_username, _settings.viewer_password.get_secret_value())


def _report_doc() -> dict:
    now = datetime(2026, 7, 8, 0, 0, tzinfo=UTC)
    return {
        "_id": "daily:2026-07-08",
        "period_type": "daily",
        "period_key": "2026-07-08",
        "generated_at": now,
        "window_start": now,
        "window_end": now,
        "conversations_analyzed": 5,
        "clusters": [
            {
                "label": "New model support",
                "representative_question": "do you support the new model",
                "sample_questions": ["do you support the new model"],
                "size": 3,
                "dominant_topic": "services",
                "coverage": "missing",
                "conversation_ids": ["cnv_1", "cnv_2", "cnv_3"],
                "proposed": {
                    "question": "Do you support the new model?",
                    "answer": "Yes.",
                    "canonical_draft_intent": "insight_abc123",
                },
            }
        ],
        "summary": "One notable gap this period.",
    }


async def test_latest_insights_empty(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/admin/insights", auth=ADMIN_AUTH)
    assert resp.status_code == 200
    assert resp.json()["report"] is None


async def test_latest_and_by_id_and_list(
    client: httpx.AsyncClient, insights_collection: Collection
) -> None:
    await insights_collection.insert_one(_report_doc())

    latest = await client.get("/api/v1/admin/insights", auth=VIEWER_AUTH)  # read: either role
    body = latest.json()["report"]
    assert body["period_key"] == "2026-07-08" and body["summary"].startswith("One notable")
    cluster = body["clusters"][0]
    assert cluster["coverage"] == "missing" and cluster["size"] == 3
    assert cluster["proposed_canonical_intent"] == "insight_abc123"

    by_id = await client.get("/api/v1/admin/insights/reports/daily:2026-07-08", auth=ADMIN_AUTH)
    assert by_id.status_code == 200 and by_id.json()["period_key"] == "2026-07-08"

    listed = await client.get("/api/v1/admin/insights/reports", auth=ADMIN_AUTH)
    reports = listed.json()["reports"]
    assert any(r["report_id"] == "daily:2026-07-08" and r["cluster_count"] == 1 for r in reports)


async def test_missing_report_404(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/admin/insights/reports/daily:1999-01-01", auth=ADMIN_AUTH)
    assert resp.status_code == 404


async def test_run_now_is_admin_only_and_audited(
    client: httpx.AsyncClient, jobs_collection: Collection, audit_collection: Collection
) -> None:
    forbidden = await client.post("/api/v1/admin/insights/run", auth=VIEWER_AUTH)
    assert forbidden.status_code == 403

    ok = await client.post("/api/v1/admin/insights/run", auth=ADMIN_AUTH)
    assert ok.status_code == 200 and ok.json()["ok"] is True
    assert (
        await jobs_collection.count_documents(
            {"type": "generate_insights", "resource_id": "refresh"}
        )
        == 1
    )
    assert await audit_collection.count_documents({"action": "run_insights"}) == 1
