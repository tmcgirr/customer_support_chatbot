"""Request repository (contracts §8, §9). Idempotent per (conversation, key)."""

from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from app.domain.requests.models import RequestRecord

Collection = AsyncIOMotorCollection[dict[str, Any]]


def _now() -> datetime:
    return datetime.now(UTC)


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

    # --- Delivery state (worker) ---

    async def get(self, request_id: str) -> RequestRecord | None:
        doc = await self._collection.find_one({"_id": request_id})
        return RequestRecord.model_validate(doc) if doc is not None else None

    async def mark_delivering(self, request_id: str, destination: str) -> None:
        # Only from a non-terminal state — never resurrect a delivered/failed request.
        await self._collection.update_one(
            {"_id": request_id, "status": {"$in": ["received", "delivering"]}},
            {
                "$set": {"status": "delivering", "destination": destination},
                "$inc": {"delivery_attempts": 1},
            },
        )

    async def list_undelivered(
        self, created_before: datetime, limit: int = 200
    ) -> list[RequestRecord]:
        """Requests stuck in received/delivering since before ``created_before`` — the
        reconciliation sweep re-enqueues or parks these (worker crash / lost enqueue)."""
        docs = (
            await self._collection.find(
                {
                    "status": {"$in": ["received", "delivering"]},
                    "created_at": {"$lt": created_before},
                }
            )
            .limit(limit)
            .to_list(length=limit)
        )
        return [RequestRecord.model_validate(doc) for doc in docs]

    async def mark_delivered(self, request_id: str, external_reference: str) -> None:
        await self._collection.update_one(
            {"_id": request_id},
            {
                "$set": {
                    "status": "delivered",
                    "external_reference": external_reference,
                    "delivered_at": _now(),
                    "last_delivery_error": None,
                }
            },
        )

    async def mark_delivery_failed(self, request_id: str, error_code: str) -> None:
        await self._collection.update_one(
            {"_id": request_id},
            {"$set": {"status": "delivery_failed", "last_delivery_error": error_code}},
        )

    async def record_delivery_error(self, request_id: str, error_code: str) -> None:
        """A transient failure that will be retried — keep status 'delivering'."""
        await self._collection.update_one(
            {"_id": request_id}, {"$set": {"last_delivery_error": error_code}}
        )

    async def reset_for_redelivery(self, request_id: str) -> bool:
        """Admin redeliver: move a parked (delivery_failed) request back to received
        so a fresh delivery job can be enqueued. Returns whether one was reset."""
        result = await self._collection.update_one(
            {"_id": request_id, "status": "delivery_failed"},
            {"$set": {"status": "received", "last_delivery_error": None}},
        )
        return result.modified_count > 0

    # --- Retention & deletion (V6) ---

    async def find_by_email(self, email: str, *, limit: int = 500) -> list[RequestRecord]:
        """All requests whose contact email matches (subject-match for a deletion)."""
        docs = (
            await self._collection.find({"contact.email": email}).limit(limit).to_list(length=limit)
        )
        return [RequestRecord.model_validate(doc) for doc in docs]

    async def redact_for_deletion(self, request_ids: list[str]) -> int:
        """Subject erasure: strip contact PII + the per-type ``fields`` payload from
        matched requests, keeping the non-PII skeleton (_id, type, status, reference,
        external_reference, timestamps) so a delivered request stays auditable and its
        downstream (CRM) reference is still known. Idempotent (already-redacted →
        matched-but-unchanged)."""
        if not request_ids:
            return 0
        result = await self._collection.update_many(
            {"_id": {"$in": request_ids}},
            {
                "$set": {
                    "contact": {"name": None, "email": None, "company": None},
                    "fields": {},
                    "deletion_status": "deleted",
                }
            },
        )
        return int(result.modified_count)

    async def delete_before(self, cutoff: datetime, *, limit: int) -> int:
        """Retention: hard-delete requests created before ``cutoff`` (contact PII
        past its retention period). Bounded per run."""
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
