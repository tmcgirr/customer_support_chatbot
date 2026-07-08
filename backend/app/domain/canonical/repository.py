"""Canonical answer repository (contracts §5, §7, §8).

An approved canonical answer for an intent wins over any generated text
(CLAUDE.md invariant #8). ``get_canonical_answer`` is the read path the model
tool uses and only ever returns *approved* records.
"""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ASCENDING, ReturnDocument

from app.domain.canonical.models import CanonicalAnswer, CanonicalMatch

Collection = AsyncIOMotorCollection[dict[str, Any]]


async def ensure_indexes(collection: Collection) -> None:
    """Idempotently create the canonical_answers index (contracts §8)."""
    await collection.create_index(
        [("intent", ASCENDING), ("status", ASCENDING)], name="intent_status"
    )


class CanonicalAnswerRepository:
    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    async def get_canonical_answer(self, intent: str) -> CanonicalMatch:
        """Return the approved canonical answer for ``intent`` (contracts §5).

        Only ``approved`` records match; a draft record or no record at all
        yields ``matched=False`` so unapproved wording is never surfaced.
        """
        doc = await self._collection.find_one({"intent": intent, "status": "approved"})
        if doc is None:
            return CanonicalMatch.unmatched()
        return CanonicalMatch.from_answer(CanonicalAnswer.model_validate(doc))

    async def upsert(self, answer: CanonicalAnswer) -> CanonicalAnswer:
        """Insert or update the canonical answer for its intent (idempotent).

        Keyed by ``intent`` so re-seeding never creates duplicates; the ``_id``
        is fixed on first insert and preserved across later upserts.
        """
        doc = answer.model_dump(by_alias=True)
        doc_id = doc.pop("_id")
        # `status` is set ONCE on insert and thereafter only changed via approve():
        # re-seeding content (even with --status draft) never downgrades an already
        # approved answer, so a re-seed can't silently disable the served baseline.
        status = doc.pop("status")
        result = await self._collection.find_one_and_update(
            {"intent": answer.intent},
            {"$set": doc, "$setOnInsert": {"_id": doc_id, "status": status}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return CanonicalAnswer.model_validate(result)

    async def get(self, intent: str) -> CanonicalAnswer | None:
        """Return the canonical answer for ``intent`` at ANY status (unlike
        ``get_canonical_answer``, which only returns approved). Used by the admin
        approve action to validate a draft exists *before* auditing/mutating."""
        doc = await self._collection.find_one({"intent": intent})
        return CanonicalAnswer.model_validate(doc) if doc else None

    async def approve(self, intent: str) -> bool:
        """Promote the draft canonical answer for ``intent`` to approved (the admin
        approval action, contracts §4). Returns whether a draft was promoted."""
        result = await self._collection.update_one(
            {"intent": intent, "status": "draft"},
            {"$set": {"status": "approved"}},
        )
        return result.modified_count > 0

    async def list_answers(self) -> list[CanonicalAnswer]:
        docs = await self._collection.find({}).to_list(length=None)
        return [CanonicalAnswer.model_validate(doc) for doc in docs]
