"""Feedback repository (contracts §8). One rating per message (idempotent)."""

from datetime import datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ASCENDING, ReturnDocument

from app.domain.feedback.models import Feedback

Collection = AsyncIOMotorCollection[dict[str, Any]]


async def ensure_indexes(collection: Collection) -> None:
    # Unique per (conversation, message): re-rating a message updates in place
    # rather than spamming duplicate rows (CLAUDE.md invariant #7).
    await collection.create_index(
        [("conversation_id", ASCENDING), ("message_id", ASCENDING)],
        name="conversation_message",
        unique=True,
    )


class FeedbackRepository:
    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    async def record(self, feedback: Feedback) -> Feedback:
        """Upsert the feedback for a message; the latest rating wins."""
        result = await self._collection.find_one_and_update(
            {"conversation_id": feedback.conversation_id, "message_id": feedback.message_id},
            {
                "$set": {
                    "rating": feedback.rating,
                    "reason": feedback.reason,
                    "comment": feedback.comment,
                },
                "$setOnInsert": {"_id": feedback.id, "created_at": feedback.created_at},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return Feedback.model_validate(result)

    # --- Retention & deletion (V6) ---

    async def delete_for_conversations(self, conversation_ids: list[str]) -> int:
        """Subject erasure cascade: drop feedback rows for the deleted conversations
        (a comment field may carry free-text PII). Idempotent."""
        if not conversation_ids:
            return 0
        result = await self._collection.delete_many({"conversation_id": {"$in": conversation_ids}})
        return int(result.deleted_count)

    async def delete_before(self, cutoff: datetime, *, limit: int) -> int:
        """Retention: hard-delete feedback created before ``cutoff``."""
        ids_to_drop = [
            doc["_id"]
            for doc in await self._collection.find({"created_at": {"$lt": cutoff}}, {"_id": 1})
            .limit(limit)
            .to_list(length=limit)
        ]
        if not ids_to_drop:
            return 0
        result = await self._collection.delete_many({"_id": {"$in": ids_to_drop}})
        return int(result.deleted_count)

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
