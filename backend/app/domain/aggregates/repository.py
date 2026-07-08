"""Daily aggregate snapshots (for the admin overview / trends).

The ``daily_aggregates`` job upserts one snapshot per UTC date — re-running the
job the same day overwrites in place (idempotent). Counts only; no PII.
"""

from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection

Collection = AsyncIOMotorCollection[dict[str, Any]]


class AggregatesRepository:
    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    async def record_daily(self, date_key: str, payload: dict[str, Any]) -> None:
        await self._collection.update_one(
            {"_id": date_key},
            {"$set": {"date": date_key, "computed_at": datetime.now(UTC), **payload}},
            upsert=True,
        )

    async def get(self, date_key: str) -> dict[str, Any] | None:
        return await self._collection.find_one({"_id": date_key})

    async def latest(self) -> dict[str, Any] | None:
        docs = await self._collection.find().sort("_id", -1).limit(1).to_list(length=1)
        return docs[0] if docs else None
