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
    run_poll_indexing,
    run_stale_lock_sweep,
)
from app.domain.knowledge.models import IndexingStatus
from app.domain.knowledge.repository import KnowledgeSourceRepository
from app.domain.requests.repository import RequestRepository
from tests.jobs.conftest import Database


class _NoPollStore:
    """A store that fails loudly if any method is called — proves run_poll_indexing
    short-circuits without touching the provider for a non-pollable source."""

    channel = "test"

    async def upload(self, *, filename: str, content: bytes) -> str:
        raise AssertionError("unexpected upload")

    async def attach(self, file_id: str, *, attributes: dict[str, str]) -> IndexingStatus:
        raise AssertionError("unexpected attach")

    async def status(self, file_id: str) -> IndexingStatus:
        raise AssertionError("must not poll a detached/inactive source")

    async def detach(self, file_id: str) -> None:
        raise AssertionError("unexpected detach")


async def test_label_conversations_labels_and_is_idempotent(db: Database) -> None:
    from app.domain.canonical.repository import CanonicalAnswerRepository
    from app.domain.conversations.models import Conversation, Message
    from app.domain.jobs.tasks import run_label_conversations
    from app.domain.requests.models import Contact, RequestRecord
    from tests.fakes import FakeAdapter

    conversations = ConversationRepository(db["conversations"])
    requests = RequestRepository(db["requests"])
    canonical = CanonicalAnswerRepository(db["canonical_answers"])
    now = datetime.now(UTC)

    # A: ended conversation with a submitted request → rules label it (no model call).
    convo_a = Conversation(id="cnv_a", status="completed", started_at=now, last_activity_at=now)
    await db["conversations"].insert_one(convo_a.model_dump(by_alias=True))
    await db["requests"].insert_one(
        RequestRecord(
            id="req_a",
            type="strategy_call",
            conversation_id="cnv_a",
            idempotency_key="k",
            reference="R",
            contact=Contact(email="a@b.com"),
            consent_version="c",
            created_at=now,
        ).model_dump(by_alias=True)
    )
    # B: ended conversation with no strong signal → model labels it.
    convo_b = Conversation(
        id="cnv_b",
        status="abandoned",
        started_at=now,
        last_activity_at=now,
        messages=[Message(id="m", role="user", content="How does AI help retail?", created_at=now)],
    )
    await db["conversations"].insert_one(convo_b.model_dump(by_alias=True))
    # C: still active → must NOT be labeled.
    convo_c = Conversation(id="cnv_c", status="active", started_at=now, last_activity_at=now)
    await db["conversations"].insert_one(convo_c.model_dump(by_alias=True))

    adapter = FakeAdapter(classify_result='{"topic": "industry", "intent": "learn"}')
    result = await run_label_conversations(conversations, requests, canonical, adapter)
    assert result == {"scanned": 2, "labeled": 2}

    a = await conversations.get_transcript("cnv_a")
    assert a is not None and a.labels is not None
    assert a.labels.intent == "request_contact" and a.labels.method == "rules"
    b = await conversations.get_transcript("cnv_b")
    assert b is not None and b.labels is not None
    assert b.labels.topic == "industry" and b.labels.method == "model"
    c = await conversations.get_transcript("cnv_c")
    assert c is not None and c.labels is None  # active is skipped

    # Idempotent: a second run finds nothing unlabeled.
    again = await run_label_conversations(conversations, requests, canonical, adapter)
    assert again == {"scanned": 0, "labeled": 0}


async def test_label_conversations_stops_at_time_budget(db: Database) -> None:
    # A zero time budget stops the loop after the first conversation, so a large residue
    # backlog can't run the handler past the worker's job timeout (it drains next run).
    from app.domain.canonical.repository import CanonicalAnswerRepository
    from app.domain.conversations.models import Conversation, Message
    from app.domain.jobs.tasks import run_label_conversations
    from tests.fakes import FakeAdapter

    now = datetime.now(UTC)
    for i in range(3):
        convo = Conversation(
            id=f"cnv_{i}",
            status="completed",
            started_at=now,
            last_activity_at=now,
            messages=[Message(id="m", role="user", content=f"Question {i}?", created_at=now)],
        )
        await db["conversations"].insert_one(convo.model_dump(by_alias=True))

    result = await run_label_conversations(
        ConversationRepository(db["conversations"]),
        RequestRepository(db["requests"]),
        CanonicalAnswerRepository(db["canonical_answers"]),
        FakeAdapter(classify_result='{"topic": "other", "intent": "learn"}'),
        time_budget_seconds=0.0,
    )
    # Deadline is already past → the loop breaks after processing exactly one.
    assert result == {"scanned": 1, "labeled": 1}


async def test_poll_indexing_noops_on_inactive_source(db: Database) -> None:
    # A source removed/replaced after approval is DETACHED; polling its status would
    # 404 and dead-letter uselessly. run_poll_indexing must no-op on lifecycle != active.
    knowledge = KnowledgeSourceRepository(db["knowledge_sources"])
    await knowledge.record_source(
        source_id="kbs_inactive",
        openai_file_id="file_x",
        vector_store_id="vs",
        title="Doc",
        category="general",
        approved=False,
        lifecycle="removed",
        indexing_status="pending",
    )
    result = await run_poll_indexing(knowledge, _NoPollStore(), source_id="kbs_inactive")
    assert result == {"status": "inactive"}


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
    marked = await run_abandonment_sweep(
        repo, abandon_seconds=86_400, anonymous_ttl_seconds=30 * 86_400
    )
    assert marked == 1
    doc = await db["conversations"].find_one({"_id": convo.id})
    assert doc is not None and doc["status"] == "abandoned"
    # An anonymous walk-away (no request outcome) gets the retention TTL stamp.
    assert doc.get("expire_at") is not None


async def test_abandonment_sweep_leaves_recent_active(db: Database) -> None:
    repo = ConversationRepository(db["conversations"])
    convo = await repo.create()  # last_activity_at = now
    assert (
        await run_abandonment_sweep(repo, abandon_seconds=86_400, anonymous_ttl_seconds=30 * 86_400)
        == 0
    )
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
