import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection

from app.domain.conversations.models import Message, Usage
from app.domain.conversations.repository import ConversationRepository

Collection = AsyncIOMotorCollection[dict[str, Any]]


def _assistant(content: str = "Hi there.", *, status: str = "completed") -> Message:
    return Message(
        id="msg_assistant",
        role="assistant",
        content=content,
        status=status,  # type: ignore[arg-type]
        created_at=datetime.now(UTC),
    )


async def test_create_and_get_transcript(repo: ConversationRepository) -> None:
    created = await repo.create(entry_page="/services", locale="en-US")
    assert created.id.startswith("cnv_")
    assert created.status == "active"
    assert created.message_count == 0

    fetched = await repo.get_transcript(created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.entry_page == "/services"
    assert fetched.active_run is None


async def test_begin_turn_started(repo: ConversationRepository) -> None:
    convo = await repo.create()
    result = await repo.begin_turn(convo.id, "Do you work with construction?", "cmid_1")

    assert result.outcome == "STARTED"
    assert result.run_id is not None
    assert result.conversation is not None
    assert result.conversation.message_count == 1
    assert result.conversation.active_run is not None
    assert result.conversation.messages[-1].role == "user"
    assert result.conversation.messages[-1].content == "Do you work with construction?"


async def test_get_missing_conversation_returns_none(repo: ConversationRepository) -> None:
    assert await repo.get_transcript("cnv_does_not_exist") is None
    result = await repo.begin_turn("cnv_does_not_exist", "hi", "cmid_x")
    assert result.outcome == "NOT_FOUND"


async def test_duplicate_client_message_id_replays(repo: ConversationRepository) -> None:
    convo = await repo.create()
    started = await repo.begin_turn(convo.id, "First question", "cmid_dup")
    assert started.outcome == "STARTED"
    # Finish the turn so the lock is clear — isolates dedupe from BUSY.
    await repo.complete_turn(convo.id, started.run_id or "", _assistant())

    replay = await repo.begin_turn(convo.id, "First question again", "cmid_dup")
    assert replay.outcome == "DUPLICATE"
    # No new user message was appended.
    assert replay.conversation is not None
    assert sum(1 for m in replay.conversation.messages if m.role == "user") == 1


async def test_duplicate_while_in_flight_returns_busy(repo: ConversationRepository) -> None:
    convo = await repo.create()
    started = await repo.begin_turn(convo.id, "q1", "cmid_1")
    assert started.outcome == "STARTED"

    # Same cmid while the run is still active and no reply exists yet -> wait, not replay.
    again = await repo.begin_turn(convo.id, "q1 retry", "cmid_1")
    assert again.outcome == "BUSY"

    # Once the turn produces a reply, the same cmid replays as DUPLICATE.
    await repo.complete_turn(convo.id, started.run_id or "", _assistant())
    replay = await repo.begin_turn(convo.id, "q1 retry", "cmid_1")
    assert replay.outcome == "DUPLICATE"


async def test_concurrent_begin_turn_exactly_one_started(repo: ConversationRepository) -> None:
    """The Checkpoint 1 gate: N simultaneous turns, exactly one STARTED."""
    convo = await repo.create()
    writers = 8

    results = await asyncio.gather(
        *(repo.begin_turn(convo.id, f"Question {i}", f"cmid_{i}") for i in range(writers))
    )
    outcomes = [r.outcome for r in results]

    assert outcomes.count("STARTED") == 1
    assert outcomes.count("BUSY") == writers - 1

    # Only the single winner's user message was appended.
    fetched = await repo.get_transcript(convo.id)
    assert fetched is not None
    assert fetched.message_count == 1
    assert sum(1 for m in fetched.messages if m.role == "user") == 1
    assert fetched.active_run is not None


async def test_cap_counts_user_messages_only(repo: ConversationRepository) -> None:
    convo = await repo.create(message_cap=2)

    first = await repo.begin_turn(convo.id, "q1", "cmid_1")
    assert first.outcome == "STARTED"
    completed = await repo.complete_turn(convo.id, first.run_id or "", _assistant())
    # A completed turn = 2 stored messages but only 1 counts toward the cap.
    assert completed is not None
    assert completed.message_count == 1
    assert len(completed.messages) == 2

    second = await repo.begin_turn(convo.id, "q2", "cmid_2")
    assert second.outcome == "STARTED"
    await repo.complete_turn(convo.id, second.run_id or "", _assistant())
    # 2 user turns == cap.

    capped = await repo.begin_turn(convo.id, "q3", "cmid_3")
    assert capped.outcome == "CAP_REACHED"


async def test_stale_lock_recovery(
    repo: ConversationRepository, conversations_collection: Collection
) -> None:
    aged = await repo.create()
    assert (await repo.begin_turn(aged.id, "q1", "cmid_1")).outcome == "STARTED"

    # A second conversation with a FRESH lock that MUST survive the sweep — this is
    # the negative case that proves the age predicate actually discriminates.
    fresh = await repo.create()
    assert (await repo.begin_turn(fresh.id, "q1", "cmid_1")).outcome == "STARTED"

    # Age only the first lock into the past, then sweep locks older than 5 minutes.
    await conversations_collection.update_one(
        {"_id": aged.id},
        {"$set": {"active_run.started_at": datetime(2020, 1, 1, tzinfo=UTC)}},
    )
    cleared = await repo.clear_stale_locks(older_than=datetime.now(UTC) - timedelta(minutes=5))
    assert cleared == 1  # exactly the aged lock, not the fresh one

    aged_after = await repo.get_transcript(aged.id)
    fresh_after = await repo.get_transcript(fresh.id)
    assert aged_after is not None and aged_after.active_run is None
    assert fresh_after is not None and fresh_after.active_run is not None

    # The recovered conversation can start a fresh turn.
    assert (await repo.begin_turn(aged.id, "q2", "cmid_2")).outcome == "STARTED"


async def test_usage_by_model_splits_chat_and_testing(repo: ConversationRepository) -> None:
    now = datetime.now(UTC)

    async def _with_usage(
        entry_page: str | None, model: str, inp: int, out: int, cmid: str
    ) -> None:
        convo = await repo.create(entry_page=entry_page)
        started = await repo.begin_turn(convo.id, "q", cmid)
        await repo.complete_turn(
            convo.id,
            started.run_id or "",
            Message(
                id=f"msg_{cmid}",
                role="assistant",
                content="a",
                status="completed",
                usage=Usage(input_tokens=inp, output_tokens=out),
                model=model,
                created_at=now,
            ),
        )

    # A production conversation (chat) and an eval conversation (testing).
    await _with_usage(None, "claude-haiku-4-5", 100, 40, "cmid_chat")
    await _with_usage("eval", "gpt-5.4-mini", 10, 5, "cmid_eval")

    rows = await repo.usage_by_model(now - timedelta(hours=1))
    by = {(r["model"], r["eval"]): r for r in rows}
    assert by[("claude-haiku-4-5", False)]["input_tokens"] == 100
    assert by[("claude-haiku-4-5", False)]["output_tokens"] == 40
    assert by[("gpt-5.4-mini", True)]["input_tokens"] == 10
    # A window that starts in the future captures nothing.
    assert await repo.usage_by_model(now + timedelta(hours=1)) == []
