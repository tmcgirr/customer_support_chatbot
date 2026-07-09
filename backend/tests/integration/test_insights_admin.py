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


async def test_latest_orders_by_generated_at_not_id(
    client: httpx.AsyncClient, insights_collection: Collection
) -> None:
    # A weekly report id sorts lexically above a daily id; "latest" must still be the most
    # recently GENERATED one (the fresh daily), not the lexically-max weekly.
    weekly = _report_doc()
    weekly["_id"] = "weekly:2026-W27"
    weekly["period_type"] = "weekly"
    weekly["period_key"] = "2026-W27"
    weekly["generated_at"] = datetime(2026, 7, 6, tzinfo=UTC)  # older
    daily = _report_doc()
    daily["generated_at"] = datetime(2026, 7, 9, tzinfo=UTC)  # newer
    await insights_collection.insert_many([weekly, daily])

    resp = await client.get("/api/v1/admin/insights", auth=ADMIN_AUTH)
    assert resp.json()["report"]["period_type"] == "daily"  # the newer one, not weekly


async def test_report_view_masks_verbatim_question_text(
    client: httpx.AsyncClient, insights_collection: Collection
) -> None:
    # representative_question / sample_questions are verbatim visitor text → masked in the
    # admin view like every other free-text field; reveal stays the audited per-record path.
    doc = _report_doc()
    doc["clusters"][0]["representative_question"] = "email me at jane@acme.com about pricing"
    doc["clusters"][0]["sample_questions"] = ["reach me at jane@acme.com"]
    # label can fall back to the raw representative question (analyze-LLM timeout) → must mask.
    doc["clusters"][0]["label"] = "email me at jane@acme.com about pricing"
    # proposed_question can also fall back to the raw question (service.py `_propose`).
    doc["clusters"][0]["proposed"]["question"] = "reply to jane@acme.com with pricing"
    await insights_collection.insert_one(doc)

    body = (await client.get("/api/v1/admin/insights", auth=ADMIN_AUTH)).json()["report"]
    cluster = body["clusters"][0]
    assert "jane@acme.com" not in cluster["representative_question"]
    assert "jane@acme.com" not in cluster["sample_questions"][0]
    assert "jane@acme.com" not in cluster["label"]
    assert "jane@acme.com" not in cluster["proposed_question"]


async def test_knowledge_gaps_ranking(
    client: httpx.AsyncClient, insights_collection: Collection
) -> None:
    def _daily(day: int, topic: str, size: int, coverage: str = "missing") -> dict:
        d = datetime(2026, 7, day, tzinfo=UTC)
        return {
            "_id": f"daily:2026-07-{day:02d}",
            "period_type": "daily",
            "period_key": f"2026-07-{day:02d}",
            "generated_at": d,
            "window_start": d,
            "window_end": d,
            "conversations_analyzed": 10,
            "conversations_in_period": 10,
            "clusters": [
                {
                    "label": topic,
                    "representative_question": f"a {topic} question",
                    "sample_questions": [f"a {topic} question"],
                    "size": size,
                    "dominant_topic": topic,
                    "coverage": coverage,
                    "conversation_ids": ["cnv_1"],
                    "proposed": None,
                }
            ],
            "summary": "s",
        }

    # pricing: 4 asks over 2 days · security: 5 asks over 1 day · covered onboarding: excluded
    await insights_collection.insert_many(
        [
            _daily(6, "onboarding", 9, coverage="covered"),
            _daily(7, "pricing", 2),
            _daily(8, "pricing", 2),
            _daily(9, "security", 5),
        ]
    )

    resp = await client.get("/api/v1/admin/insights/gaps", auth=VIEWER_AUTH)  # read: either role
    assert resp.status_code == 200
    body = resp.json()
    assert body["daily_reports"] == 4  # covered onboarding is still a report that was scanned
    keys = [g["key"] for g in body["gaps"]]
    assert keys == ["topic:security", "topic:pricing"]  # magnitude 5 > 4
    pricing = next(g for g in body["gaps"] if g["key"] == "topic:pricing")
    assert pricing["total_asked"] == 4 and pricing["days_seen"] == 2
    assert all(g["coverage"] != "covered" for g in body["gaps"])


async def test_knowledge_gaps_masks_question_text(
    client: httpx.AsyncClient, insights_collection: Collection
) -> None:
    doc = _report_doc()
    # No dominant_topic → the merge key becomes "label:<label>", and the label itself falls
    # back to the raw question on an analyze-LLM timeout — so key, label AND the question
    # can each carry the email. All three must be masked.
    doc["clusters"][0]["dominant_topic"] = None
    doc["clusters"][0]["label"] = "contact bob@corp.com re the new model"
    doc["clusters"][0]["representative_question"] = "contact bob@corp.com re the new model"
    doc["clusters"][0]["proposed"]["question"] = "email bob@corp.com about the new model"
    await insights_collection.insert_one(doc)

    body = (await client.get("/api/v1/admin/insights/gaps", auth=ADMIN_AUTH)).json()
    assert body["gaps"], "expected the missing-coverage cluster to surface as a gap"
    gap = body["gaps"][0]
    assert "bob@corp.com" not in gap["representative_question"]
    assert "bob@corp.com" not in gap["label"]
    assert "bob@corp.com" not in gap["key"]
    assert "bob@corp.com" not in gap["proposed_question"]


async def test_run_now_dedups_a_pending_refresh(
    client: httpx.AsyncClient, jobs_collection: Collection
) -> None:
    first = await client.post("/api/v1/admin/insights/run", auth=ADMIN_AUTH)
    second = await client.post("/api/v1/admin/insights/run", auth=ADMIN_AUTH)
    assert first.status_code == 200 and second.status_code == 200
    assert "already in progress" in second.json()["detail"]
    # The second click did NOT enqueue a duplicate refresh job.
    assert (
        await jobs_collection.count_documents(
            {"type": "generate_insights", "resource_id": "refresh"}
        )
        == 1
    )


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
