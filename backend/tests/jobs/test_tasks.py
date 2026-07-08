"""Scheduled-task tests: each periodic maintenance task, run directly against a
real MongoDB (no worker), asserting its idempotent effect."""

from datetime import UTC, datetime, timedelta

from app.domain.aggregates.repository import AggregatesRepository
from app.domain.conversations.repository import ConversationRepository
from app.domain.feedback.models import Feedback
from app.domain.feedback.repository import FeedbackRepository
from app.domain.jobs.tasks import (
    run_abandonment_sweep,
    run_daily_aggregates,
    run_knowledge_review_reminder,
    run_stale_lock_sweep,
)
from app.domain.knowledge.repository import KnowledgeSourceRepository
from app.domain.requests.repository import RequestRepository
from tests.jobs.conftest import Database


async def test_stale_lock_sweep_clears_leaked_lock(db: Database) -> None:
    repo = ConversationRepository(db["conversations"])
    convo = await repo.create()
    await db["conversations"].update_one(
        {"_id": convo.id},
        {
            "$set": {
                "active_run": {"run_id": "r", "started_at": datetime.now(UTC) - timedelta(hours=1)}
            }
        },
    )
    cleared = await run_stale_lock_sweep(repo, lock_stale_seconds=120)
    assert cleared == 1
    doc = await db["conversations"].find_one({"_id": convo.id})
    assert doc is not None and doc["active_run"] is None


async def test_abandonment_sweep_marks_inactive_conversations(db: Database) -> None:
    repo = ConversationRepository(db["conversations"])
    convo = await repo.create()
    await db["conversations"].update_one(
        {"_id": convo.id}, {"$set": {"last_activity_at": datetime.now(UTC) - timedelta(days=2)}}
    )
    marked = await run_abandonment_sweep(repo, abandon_seconds=86_400)
    assert marked == 1
    doc = await db["conversations"].find_one({"_id": convo.id})
    assert doc is not None and doc["status"] == "abandoned"


async def test_abandonment_sweep_leaves_recent_active(db: Database) -> None:
    repo = ConversationRepository(db["conversations"])
    convo = await repo.create()  # last_activity_at = now
    assert await run_abandonment_sweep(repo, abandon_seconds=86_400) == 0
    doc = await db["conversations"].find_one({"_id": convo.id})
    assert doc is not None and doc["status"] == "active"


async def test_knowledge_review_reminder_flags_overdue_sources(db: Database) -> None:
    repo = KnowledgeSourceRepository(db["knowledge_sources"])
    past = datetime.now(UTC) - timedelta(days=1)
    future = datetime.now(UTC) + timedelta(days=30)
    await repo.record_source(
        source_id="kbs_overdue",
        openai_file_id="file_1",
        vector_store_id="vs",
        title="Overdue",
        category="company_overview",
        review_date=past,
    )
    await repo.record_source(
        source_id="kbs_fresh",
        openai_file_id="file_2",
        vector_store_id="vs",
        title="Fresh",
        category="company_overview",
        review_date=future,
    )
    due = await run_knowledge_review_reminder(repo)
    assert due == ["kbs_overdue"]


async def test_daily_aggregates_writes_a_snapshot(db: Database) -> None:
    conversations = ConversationRepository(db["conversations"])
    requests = RequestRepository(db["requests"])
    feedback = FeedbackRepository(db["feedback"])
    aggregates = AggregatesRepository(db["aggregates"])
    await conversations.create()
    await feedback.record(
        Feedback(
            id="fbk_1",
            conversation_id="cnv_x",
            message_id="msg_x",
            rating="helpful",
            created_at=datetime.now(UTC),
        )
    )

    payload = await run_daily_aggregates(conversations, requests, feedback, aggregates)
    assert payload["conversations"]["total"] == 1
    assert payload["feedback"]["total"] == 1

    date_key = datetime.now(UTC).date().isoformat()
    snapshot = await aggregates.get(date_key)
    assert snapshot is not None
    assert snapshot["conversations"]["total"] == 1

    # Idempotent: re-running the same day overwrites in place (no duplicate snapshot).
    await run_daily_aggregates(conversations, requests, feedback, aggregates)
    assert await db["aggregates"].count_documents({}) == 1
