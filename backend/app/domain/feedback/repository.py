"""Feedback repository (contracts §8). One rating per message (idempotent)."""

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
