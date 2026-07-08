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
from app.domain.conversations.models import Conversation, Message

Collection = AsyncIOMotorCollection[dict[str, Any]]

BeginTurnOutcome = Literal["STARTED", "DUPLICATE", "BUSY", "CAP_REACHED", "NOT_FOUND"]


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
        """Release locks whose run started before ``older_than``. Returns count."""
        result = await self._collection.update_many(
            {"active_run": {"$ne": None}, "active_run.started_at": {"$lt": older_than}},
            {"$set": {"active_run": None}},
        )
        return int(result.modified_count)

    async def get_transcript(self, conversation_id: str) -> Conversation | None:
        doc = await self._collection.find_one({"_id": conversation_id})
        return Conversation.model_validate(doc) if doc is not None else None
