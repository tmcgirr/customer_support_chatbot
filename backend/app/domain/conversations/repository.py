"""Conversation repository — single-document operations (ADR §3.1, ADR-015).

Every mutation is one atomic operation on the conversation document. The turn
loop's lock + user-message append + duplicate check + cap are enforced in a
single ``find_one_and_update`` — there is no second lock and no messages
collection.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ASCENDING, DESCENDING, ReturnDocument

from app.core import ids
from app.core.config import get_settings
from app.domain.conversations.models import Conversation, ConversationLabels, Message

Collection = AsyncIOMotorCollection[dict[str, Any]]

BeginTurnOutcome = Literal["STARTED", "DUPLICATE", "BUSY", "CAP_REACHED", "NOT_FOUND"]

# Outcomes that mean a PII-bearing request was created from the conversation. Such
# conversations are NOT given an anonymous-retention TTL (they live with their
# request's lifecycle); only truly anonymous walk-aways auto-expire.
REQUEST_CONVERSION_OUTCOMES = (
    "strategy_call_requested",
    "support_request_created",
    "human_escalation_created",
)


@dataclass(frozen=True)
class BeginTurnResult:
    outcome: BeginTurnOutcome
    conversation: Conversation | None = None
    run_id: str | None = None
    user_message: Message | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _has_assistant_reply(conversation: Conversation, cmid: str) -> bool:
    index = next(
        (i for i, m in enumerate(conversation.messages) if m.client_message_id == cmid), None
    )
    if index is None:
        return False
    return any(m.role == "assistant" for m in conversation.messages[index + 1 :])


async def ensure_indexes(collection: Collection) -> None:
    """Idempotently create the conversation indexes (contracts §8)."""
    await collection.create_index(
        [("status", ASCENDING), ("last_activity_at", DESCENDING)], name="status_activity"
    )
    await collection.create_index(
        [("outcome", ASCENDING), ("started_at", DESCENDING)], name="outcome_started"
    )
    await collection.create_index(
        [("messages.client_message_id", ASCENDING)], name="cmid", sparse=True
    )
    # Conditional TTL: only docs with an ``expire_at`` (set on anonymous abandoned
    # conversations by mark_abandoned) are auto-purged; all others have no expire_at
    # and are never touched by the TTL monitor (contracts §8, V6 retention).
    await collection.create_index(
        [("expire_at", ASCENDING)], name="anonymous_ttl", expireAfterSeconds=0, sparse=True
    )


class ConversationRepository:
    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    async def create(
        self,
        *,
        entry_page: str | None = None,
        locale: str | None = None,
        consent_version: str | None = None,
        message_cap: int | None = None,
        prompt_version: str | None = None,
        model: str | None = None,
    ) -> Conversation:
        now = _now()
        conversation = Conversation(
            id=ids.conversation_id(),
            status="active",
            entry_page=entry_page,
            locale=locale,
            consent_version=consent_version,
            message_cap=message_cap if message_cap is not None else get_settings().message_cap,
            prompt_version=prompt_version,
            model=model,
            started_at=now,
            last_activity_at=now,
        )
        await self._collection.insert_one(conversation.model_dump(by_alias=True))
        return conversation

    async def begin_turn(
        self, conversation_id: str, content: str, client_message_id: str
    ) -> BeginTurnResult:
        """Atomically acquire the run lock and append the pending user message.

        The single filter enforces all four preconditions at once: the document
        exists, no run is active, this client_message_id has not been seen, and
        the message cap has not been reached. Exactly one concurrent caller can
        match — everyone else is diagnosed into DUPLICATE / BUSY / CAP_REACHED.
        """
        now = _now()
        run_identifier = ids.run_id()
        user_message = Message(
            id=ids.message_id(),
            role="user",
            content=content,
            client_message_id=client_message_id,
            status="completed",
            created_at=now,
        )
        result = await self._collection.find_one_and_update(
            {
                "_id": conversation_id,
                "active_run": None,
                "messages.client_message_id": {"$ne": client_message_id},
                "$expr": {"$lt": ["$message_count", "$message_cap"]},
            },
            {
                "$set": {
                    "active_run": {"run_id": run_identifier, "started_at": now},
                    "last_activity_at": now,
                },
                "$push": {"messages": user_message.model_dump()},
                "$inc": {"message_count": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if result is not None:
            return BeginTurnResult(
                "STARTED",
                conversation=Conversation.model_validate(result),
                run_id=run_identifier,
                user_message=user_message,
            )

        # No match — read the document once to report *why* (best-effort; the
        # atomic op already guaranteed correctness, this only picks the message).
        existing = await self._collection.find_one({"_id": conversation_id})
        if existing is None:
            return BeginTurnResult("NOT_FOUND")
        conversation = Conversation.model_validate(existing)
        is_duplicate = any(m.client_message_id == client_message_id for m in conversation.messages)
        if is_duplicate:
            # Replay only if the original produced a reply. If it is still in
            # flight (lock held, no assistant yet), the caller must wait rather
            # than receive a bogus "completed with no answer" replay.
            in_flight = conversation.active_run is not None and not _has_assistant_reply(
                conversation, client_message_id
            )
            if in_flight:
                return BeginTurnResult("BUSY", conversation=conversation)
            return BeginTurnResult("DUPLICATE", conversation=conversation)
        # Cap is terminal, so it takes precedence over the transient busy state.
        if conversation.message_count >= conversation.message_cap:
            return BeginTurnResult("CAP_REACHED", conversation=conversation)
        # active_run set, or a lost race between the failed update and this read.
        return BeginTurnResult("BUSY", conversation=conversation)

    async def complete_turn(
        self, conversation_id: str, run_id: str, assistant_message: Message
    ) -> Conversation | None:
        """Append the assistant reply and clear the lock for this run."""
        return await self._finish_turn(conversation_id, run_id, assistant_message)

    async def fail_turn(
        self, conversation_id: str, run_id: str, assistant_message: Message
    ) -> Conversation | None:
        """Append a failed assistant message (with error_code) and clear the lock."""
        return await self._finish_turn(conversation_id, run_id, assistant_message)

    async def _finish_turn(
        self, conversation_id: str, run_id: str, assistant_message: Message
    ) -> Conversation | None:
        now = _now()
        # message_count tracks USER messages only (contract §3.1: begin increments,
        # finish does not), so the cap bounds user turns. No $inc here.
        result = await self._collection.find_one_and_update(
            {"_id": conversation_id, "active_run.run_id": run_id},
            {
                "$push": {"messages": assistant_message.model_dump()},
                "$set": {"active_run": None, "last_activity_at": now},
            },
            return_document=ReturnDocument.AFTER,
        )
        return Conversation.model_validate(result) if result is not None else None

    async def clear_stale_locks(self, older_than: datetime) -> int:
        """Release locks whose run started before ``older_than``. Returns count.

        Global sweep used by ``scripts/sweep_locks.py`` for operational cleanup.
        """
        result = await self._collection.update_many(
            {"active_run": {"$ne": None}, "active_run.started_at": {"$lt": older_than}},
            {"$set": {"active_run": None}},
        )
        return int(result.modified_count)

    async def touch_lock(self, conversation_id: str, run_id: str) -> None:
        """Heartbeat: refresh this run's lock timestamp so a live (slow) turn is
        never mistaken for a leaked one by the stale-lock sweep. No-op if the
        lock is gone or belongs to another run."""
        await self._collection.update_one(
            {"_id": conversation_id, "active_run.run_id": run_id},
            {"$set": {"active_run.started_at": _now()}},
        )

    async def clear_stale_lock(self, conversation_id: str, older_than: datetime) -> bool:
        """Release a single conversation's lock iff its run is older than
        ``older_than`` (leaked by a crashed turn). Returns whether one was cleared.

        Targeted variant for the opportunistic recovery on the send path — it
        touches only the one document, never a hot-path collection scan.
        """
        result = await self._collection.update_one(
            {
                "_id": conversation_id,
                "active_run": {"$ne": None},
                "active_run.started_at": {"$lt": older_than},
            },
            {"$set": {"active_run": None}},
        )
        return result.modified_count > 0

    async def mark_abandoned(self, inactive_before: datetime, *, anonymous_ttl_seconds: int) -> int:
        """Mark still-active conversations with no activity since ``inactive_before``
        as abandoned (feeds outcome metrics). Distinct from retention deletion (V6).

        For truly ANONYMOUS abandoned conversations (no request was created), also
        stamp ``expire_at = last_activity_at + anonymous_ttl_seconds`` so the TTL
        index auto-purges them per approved retention (contracts §8). Conversations
        that converted to a request get no TTL — they live with their request.
        Returns the count updated."""
        ttl_ms = anonymous_ttl_seconds * 1000
        result = await self._collection.update_many(
            {"status": "active", "last_activity_at": {"$lt": inactive_before}},
            [
                {
                    "$set": {
                        "status": "abandoned",
                        # Converted conversations get NO expire_at ($$REMOVE omits the
                        # field entirely, so they stay out of the sparse TTL index);
                        # anonymous walk-aways expire at last_activity + the TTL.
                        "expire_at": {
                            "$cond": [
                                {"$in": ["$outcome", list(REQUEST_CONVERSION_OUTCOMES)]},
                                "$$REMOVE",
                                {"$add": ["$last_activity_at", ttl_ms]},
                            ]
                        },
                    }
                }
            ],
        )
        return int(result.modified_count)

    # --- Retention & deletion (V6) ---

    async def delete_before(
        self,
        cutoff: datetime,
        *,
        limit: int,
        statuses: list[str] | None = None,
        exclude_outcomes: list[str] | None = None,
    ) -> int:
        """Retention: hard-delete conversations with no activity since ``cutoff``
        (optionally only those in ``statuses``, and never those whose ``outcome`` is
        in ``exclude_outcomes``). Bounded by ``limit`` per run so a sweep never takes
        an unbounded delete lock. Aggregates already snapshot the counts, so history
        isn't lost.

        ``exclude_outcomes`` guards the short abandoned-retention class from reaping a
        conversation that CONVERTED to a request — those must live to the long backstop
        alongside their request, never be deleted at the 30-day anonymous period."""
        query: dict[str, Any] = {"last_activity_at": {"$lt": cutoff}}
        if statuses is not None:
            query["status"] = {"$in": statuses}
        if exclude_outcomes:
            query["outcome"] = {"$nin": exclude_outcomes}
        ids_to_drop = [
            doc["_id"]
            for doc in await self._collection.find(query, {"_id": 1})
            .limit(limit)
            .to_list(length=limit)
        ]
        if not ids_to_drop:
            return 0
        result = await self._collection.delete_many({"_id": {"$in": ids_to_drop}})
        return int(result.deleted_count)

    async def redact_for_deletion(self, conversation_ids: list[str]) -> int:
        """Subject erasure (privacy_delete job): turn matched conversations into a
        redacting tombstone — status ``deleted``, PII-bearing fields cleared — while
        keeping the _id, timestamps, and non-PII outcome so the erasure is provable
        and metrics stay consistent. Idempotent: an already-``deleted`` doc is skipped."""
        if not conversation_ids:
            return 0
        result = await self._collection.update_many(
            {"_id": {"$in": conversation_ids}, "status": {"$ne": "deleted"}},
            {
                "$set": {
                    "status": "deleted",
                    "deletion_status": "deleted",
                    "messages": [],
                    "unsupported_questions": [],
                    "entry_page": None,
                    "locale": None,
                    "active_run": None,
                }
            },
        )
        return int(result.modified_count)

    async def get_transcript(self, conversation_id: str) -> Conversation | None:
        doc = await self._collection.find_one({"_id": conversation_id})
        return Conversation.model_validate(doc) if doc is not None else None

    async def set_outcome(self, conversation_id: str, outcome: str) -> None:
        """Record the conversation outcome when a request is created (contracts §7)."""
        await self._collection.update_one(
            {"_id": conversation_id},
            {"$set": {"outcome": outcome, "last_activity_at": _now()}},
        )

    async def add_unsupported_question(self, conversation_id: str, question: str) -> None:
        """Record a verbatim unsupported question for the admin unresolved list (§7)."""
        await self._collection.update_one(
            {"_id": conversation_id},
            {"$push": {"unsupported_questions": {"question": question, "at": _now()}}},
        )

    # --- Analytics labeling (V1.5, worker-owned) ---

    # Terminal, non-deleted states a conversation can be labeled in.
    _ENDED_STATUSES = ("completed", "abandoned", "blocked")

    async def list_unlabeled_ended(self, *, limit: int) -> list[Conversation]:
        """Ended conversations that have no computed labels yet (oldest activity first,
        so the backlog drains FIFO). ``{labels: null}`` matches both missing and null."""
        docs = (
            await self._collection.find(
                {"status": {"$in": list(self._ENDED_STATUSES)}, "labels": None}
            )
            .sort("last_activity_at", ASCENDING)
            .limit(limit)
            .to_list(length=limit)
        )
        return [Conversation.model_validate(doc) for doc in docs]

    async def set_labels(self, conversation_id: str, labels: ConversationLabels) -> None:
        """Attach computed topic/intent labels (idempotent overwrite). Does NOT touch
        last_activity_at — a background annotation must not resurrect a conversation."""
        await self._collection.update_one(
            {"_id": conversation_id}, {"$set": {"labels": labels.model_dump()}}
        )

    async def list_ended_in_window(
        self, start: datetime, end: datetime, *, limit: int
    ) -> list[Conversation]:
        """Ended conversations whose last activity falls in [start, end) — the membership
        of an insights report for that period. Anchored on last_activity_at (fixed once a
        conversation ends), so a past period's set is stable across re-runs."""
        docs = (
            await self._collection.find(
                {
                    "status": {"$in": list(self._ENDED_STATUSES)},
                    "last_activity_at": {"$gte": start, "$lt": end},
                }
            )
            .sort("last_activity_at", ASCENDING)
            .limit(limit)
            .to_list(length=limit)
        )
        return [Conversation.model_validate(doc) for doc in docs]

    # --- Read-only admin queries ---

    async def total(self) -> int:
        return await self._collection.count_documents({})

    async def count_by(self, field: str) -> dict[str, int]:
        cursor = self._collection.aggregate(
            [{"$group": {"_id": f"${field}", "count": {"$sum": 1}}}]
        )
        return {
            (str(doc["_id"]) if doc["_id"] is not None else "unset"): int(doc["count"])
            for doc in await cursor.to_list(length=None)
        }

    async def list_recent(self, limit: int = 100) -> list[Conversation]:
        docs = (
            await self._collection.find()
            .sort("last_activity_at", -1)
            .limit(limit)
            .to_list(length=limit)
        )
        return [Conversation.model_validate(doc) for doc in docs]

    async def count_unsupported(self) -> int:
        """Total unsupported questions across all conversations — a server-side sum, so
        it neither saturates at a list limit nor materializes rows (used by /monitoring)."""
        pipeline: list[dict[str, Any]] = [
            {"$match": {"unsupported_questions.0": {"$exists": True}}},
            {"$group": {"_id": None, "n": {"$sum": {"$size": "$unsupported_questions"}}}},
        ]
        docs = await self._collection.aggregate(pipeline).to_list(length=1)
        return int(docs[0]["n"]) if docs else 0

    async def list_unsupported(self, limit: int = 100) -> list[dict[str, Any]]:
        pipeline: list[dict[str, Any]] = [
            {"$match": {"unsupported_questions.0": {"$exists": True}}},
            {"$unwind": "$unsupported_questions"},
            {
                "$project": {
                    "_id": 0,
                    "conversation_id": "$_id",
                    "question": "$unsupported_questions.question",
                    "at": "$unsupported_questions.at",
                }
            },
            {"$sort": {"at": -1}},
            {"$limit": limit},
        ]
        return await self._collection.aggregate(pipeline).to_list(length=limit)
