"""Privacy-request repository (contracts §7, §8).

Records access/deletion requests and their verification + fulfillment state. All
state transitions are guarded single-document updates so a replayed worker job or
a double-clicked admin verify can't advance the same request twice.
"""

from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ASCENDING, DESCENDING, ReturnDocument

from app.core import ids
from app.domain.privacy.models import PrivacyRequest, PrivacyRequestType

Collection = AsyncIOMotorCollection[dict[str, Any]]


def _now() -> datetime:
    return datetime.now(UTC)


async def ensure_indexes(collection: Collection) -> None:
    await collection.create_index([("created_at", DESCENDING)], name="created")
    await collection.create_index(
        [("requester_email", ASCENDING), ("created_at", DESCENDING)], name="email_created"
    )
    await collection.create_index(
        [("status", ASCENDING), ("verification_status", ASCENDING)], name="status_verification"
    )


class PrivacyRequestRepository:
    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    async def create(
        self, *, request_type: PrivacyRequestType, requester_email: str, conversation_id: str | None
    ) -> PrivacyRequest:
        record = PrivacyRequest(
            id=ids.privacy_request_id(),
            type=request_type,
            conversation_id=conversation_id,
            requester_email=requester_email,
            verification_status="pending",
            status="open",
            created_at=_now(),
        )
        await self._collection.insert_one(record.model_dump(by_alias=True))
        return record

    async def get(self, request_id: str) -> PrivacyRequest | None:
        doc = await self._collection.find_one({"_id": request_id})
        return PrivacyRequest.model_validate(doc) if doc is not None else None

    async def mark_verified(self, request_id: str, *, verified_by: str) -> PrivacyRequest | None:
        """Confirm identity (admin action). Guarded on verification_status=pending so
        a second verify is a no-op. Returns the updated record, or None if it wasn't
        pending (already verified/rejected/gone)."""
        doc = await self._collection.find_one_and_update(
            {"_id": request_id, "verification_status": "pending"},
            {
                "$set": {
                    "verification_status": "verified",
                    "verified_by": verified_by,
                    "verified_at": _now(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return PrivacyRequest.model_validate(doc) if doc is not None else None

    async def mark_completed(self, request_id: str, *, result_counts: dict[str, int]) -> bool:
        """Fulfillment done. Guarded on status=open so a replayed job doesn't
        re-stamp (and the worker treats an already-completed request as a no-op)."""
        result = await self._collection.update_one(
            {"_id": request_id, "status": "open"},
            {
                "$set": {
                    "status": "completed",
                    "result_counts": result_counts,
                    "completed_at": _now(),
                    "last_error": None,
                }
            },
        )
        return result.modified_count > 0

    async def mark_failed(self, request_id: str, *, error_code: str) -> bool:
        result = await self._collection.update_one(
            {"_id": request_id, "status": "open"},
            {"$set": {"status": "failed", "last_error": error_code}},
        )
        return result.modified_count > 0

    async def list_verified_open(
        self, *, verified_before: datetime, limit: int = 200
    ) -> list[PrivacyRequest]:
        """Verified deletion requests still open (not completed/failed) whose verify is
        older than ``verified_before`` — the reconcile sweep re-enqueues these when the
        erasure job was lost (crash between verify-commit and enqueue), so a verified
        erasure is never silently dropped (invariant #13)."""
        docs = (
            await self._collection.find(
                {
                    "type": "deletion",
                    "verification_status": "verified",
                    "status": "open",
                    "verified_at": {"$lt": verified_before},
                }
            )
            .limit(limit)
            .to_list(length=limit)
        )
        return [PrivacyRequest.model_validate(doc) for doc in docs]

    async def delete_before(self, cutoff: datetime, *, limit: int) -> int:
        """Retention: drop completed/failed privacy requests older than ``cutoff``.
        Open requests are never expired (they still need action)."""
        ids_to_drop = [
            doc["_id"]
            for doc in await self._collection.find(
                {"status": {"$in": ["completed", "failed"]}, "created_at": {"$lt": cutoff}},
                {"_id": 1},
            )
            .limit(limit)
            .to_list(length=limit)
        ]
        if not ids_to_drop:
            return 0
        result = await self._collection.delete_many({"_id": {"$in": ids_to_drop}})
        return int(result.deleted_count)

    # --- Read-only admin queries ---

    async def counts_by_status(self) -> dict[str, int]:
        """status -> count, for the monitoring endpoint (no PII)."""
        cursor = self._collection.aggregate([{"$group": {"_id": "$status", "count": {"$sum": 1}}}])
        return {str(doc["_id"]): int(doc["count"]) for doc in await cursor.to_list(length=None)}

    async def list_recent(self, limit: int = 100) -> list[PrivacyRequest]:
        docs = (
            await self._collection.find().sort("created_at", -1).limit(limit).to_list(length=limit)
        )
        return [PrivacyRequest.model_validate(doc) for doc in docs]
