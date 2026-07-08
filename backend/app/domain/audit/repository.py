"""Audit repository — append-only (contracts §4). Records are inserted, never
updated or deleted."""

from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ASCENDING, DESCENDING

from app.core import ids
from app.core.masking import mask_pii_in_text
from app.domain.audit.models import AuditAction, AuditRecord

Collection = AsyncIOMotorCollection[dict[str, Any]]


async def ensure_indexes(collection: Collection) -> None:
    await collection.create_index([("at", DESCENDING)], name="at")
    await collection.create_index(
        [("target_type", ASCENDING), ("target_id", ASCENDING)], name="target"
    )


class AuditRepository:
    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    async def record(
        self,
        *,
        actor: str,
        role: str,
        action: AuditAction,
        target_type: str,
        target_id: str,
        reason: str | None = None,
    ) -> AuditRecord:
        record = AuditRecord(
            id=ids.prefixed_id("aud"),
            actor=actor,
            role=role,
            action=action,
            target_type=target_type,
            target_id=target_id,
            # reason is operator free-text; mask any email/phone so no PII lands
            # in the audit trail at rest or via GET /audit (invariant #5).
            reason=mask_pii_in_text(reason) if reason else reason,
            at=datetime.now(UTC),
        )
        await self._collection.insert_one(record.model_dump(by_alias=True))
        return record

    async def list_recent(self, limit: int = 100) -> list[AuditRecord]:
        docs = await self._collection.find().sort("at", -1).limit(limit).to_list(length=limit)
        return [AuditRecord.model_validate(doc) for doc in docs]
