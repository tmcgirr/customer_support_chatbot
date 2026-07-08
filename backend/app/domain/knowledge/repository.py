"""Knowledge source repository — governance metadata (contracts §7, §8).

MongoDB owns the record of every approved source. Writes come from the manual
``scripts/upload_knowledge.py`` sync (a service at V1, ADR-007); this layer is
the single place that touches the ``knowledge_sources`` collection.
"""

from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ASCENDING, ReturnDocument

from app.domain.knowledge.models import (
    IndexingStatus,
    KnowledgeLifecycle,
    KnowledgeSource,
)

Collection = AsyncIOMotorCollection[dict[str, Any]]


def _now() -> datetime:
    return datetime.now(UTC)


async def ensure_indexes(collection: Collection) -> None:
    """Idempotently create the knowledge_sources indexes (contracts §8)."""
    # Unique + sparse: one record per provider file; docs without a file id
    # (should not occur in normal flow) are simply not indexed rather than
    # colliding on a null key.
    await collection.create_index(
        [("openai_file_id", ASCENDING)], name="openai_file_id", unique=True, sparse=True
    )
    await collection.create_index(
        [("lifecycle", ASCENDING), ("category", ASCENDING)], name="lifecycle_category"
    )
    await collection.create_index([("review_date", ASCENDING)], name="review_date")


class KnowledgeSourceRepository:
    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    async def record_source(
        self,
        *,
        source_id: str,
        openai_file_id: str,
        vector_store_id: str,
        title: str,
        category: str,
        language: str = "en",
        approved: bool = True,
        lifecycle: KnowledgeLifecycle = "active",
        indexing_status: IndexingStatus = "indexed",
        source_url: str | None = None,
        version: str = "1",
        owner: str = "cadre",
        effective_date: datetime | None = None,
        review_date: datetime | None = None,
        checksum: str | None = None,
    ) -> KnowledgeSource:
        """Upsert the governance record for a file, keyed by ``openai_file_id``.

        ``source_id`` is the public ``kbs_`` id and becomes the ``_id`` — the SAME
        id stamped into the vector-store file attributes, so a message citation's
        ``source_id`` joins back to this record (contracts §7). It and
        ``created_at`` are fixed on first write; re-recording the same file id
        updates mutable metadata in place.
        """
        now = _now()
        result = await self._collection.find_one_and_update(
            {"openai_file_id": openai_file_id},
            {
                "$setOnInsert": {
                    "_id": source_id,
                    "created_at": now,
                },
                "$set": {
                    "title": title,
                    "category": category,
                    "audience": "public",
                    "language": language,
                    "approved": approved,
                    "lifecycle": lifecycle,
                    "indexing_status": indexing_status,
                    "vector_store_id": vector_store_id,
                    "source_url": source_url,
                    "version": version,
                    "owner": owner,
                    "effective_date": effective_date,
                    "review_date": review_date,
                    "checksum": checksum,
                    "updated_at": now,
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return KnowledgeSource.model_validate(result)

    async def list_sources(self) -> list[KnowledgeSource]:
        """Every recorded source, newest first (``_id`` is a time-sortable ULID)."""
        docs = await self._collection.find().sort("_id", -1).to_list(length=None)
        return [KnowledgeSource.model_validate(doc) for doc in docs]

    async def list_due_for_review(self, as_of: datetime) -> list[KnowledgeSource]:
        """Active sources whose ``review_date`` has passed — the knowledge-review
        reminder job surfaces these for a content owner to re-approve (contracts §7)."""
        docs = await self._collection.find(
            {"review_date": {"$lt": as_of}, "lifecycle": "active"}
        ).to_list(length=None)
        return [KnowledgeSource.model_validate(doc) for doc in docs]
