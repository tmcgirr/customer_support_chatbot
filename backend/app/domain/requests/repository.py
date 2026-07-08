"""Request repository (contracts §8, §9). Idempotent per (conversation, key)."""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from app.domain.requests.models import RequestRecord

Collection = AsyncIOMotorCollection[dict[str, Any]]


async def ensure_indexes(collection: Collection) -> None:
    # Idempotency is scoped to the conversation (the session boundary), so the same
    # key used in two different conversations never collides.
    await collection.create_index(
        [("conversation_id", ASCENDING), ("idempotency_key", ASCENDING)],
        name="conversation_idempotency_key",
        unique=True,
    )
    await collection.create_index(
        [("type", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)],
        name="type_status_created",
    )
    await collection.create_index(
        [("contact.email", ASCENDING), ("created_at", DESCENDING)], name="email_created"
    )
    await collection.create_index(
        [("external_reference", ASCENDING)], name="external_reference", sparse=True
    )


class RequestRepository:
    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    async def find_by_key(self, conversation_id: str, idempotency_key: str) -> RequestRecord | None:
        doc = await self._collection.find_one(
            {"conversation_id": conversation_id, "idempotency_key": idempotency_key}
        )
        return RequestRecord.model_validate(doc) if doc is not None else None

    async def create_or_replay(self, record: RequestRecord) -> tuple[RequestRecord, bool]:
        """Insert the request, or replay the original if the key was already used
        in this conversation. Returns ``(record, is_duplicate)``.

        Safe under concurrent submissions of the same (conversation, key): the
        unique index makes the loser of the race get a DuplicateKeyError and replay
        the stored record (contracts §9).
        """
        key_filter = {
            "conversation_id": record.conversation_id,
            "idempotency_key": record.idempotency_key,
        }
        existing = await self._collection.find_one(key_filter)
        if existing is not None:
            return RequestRecord.model_validate(existing), True
        try:
            await self._collection.insert_one(record.model_dump(by_alias=True))
            return record, False
        except DuplicateKeyError:
            existing = await self._collection.find_one(key_filter)
            assert existing is not None
            return RequestRecord.model_validate(existing), True

    # --- Read-only admin queries ---

    async def total(self) -> int:
        return await self._collection.count_documents({})

    async def count_by(self, field: str) -> dict[str, int]:
        cursor = self._collection.aggregate(
            [{"$group": {"_id": f"${field}", "count": {"$sum": 1}}}]
        )
        return {str(doc["_id"]): int(doc["count"]) for doc in await cursor.to_list(length=None)}

    async def list_filtered(
        self,
        type_filter: str | None = None,
        status_filter: str | None = None,
        limit: int = 100,
    ) -> list[RequestRecord]:
        query: dict[str, Any] = {}
        if type_filter:
            query["type"] = type_filter
        if status_filter:
            query["status"] = status_filter
        docs = (
            await self._collection.find(query)
            .sort("created_at", -1)
            .limit(limit)
            .to_list(length=limit)
        )
        return [RequestRecord.model_validate(doc) for doc in docs]
