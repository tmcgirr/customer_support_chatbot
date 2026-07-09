"""Insights-report repository — dated snapshots (one per UTC day, idempotent overwrite),
mirroring ``daily_aggregates``. The worker writes; the admin API reads."""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ASCENDING

from app.domain.insights.models import InsightsReport

Collection = AsyncIOMotorCollection[dict[str, Any]]


async def ensure_indexes(collection: Collection) -> None:
    await collection.create_index([("generated_at", ASCENDING)], name="generated_at")


class InsightsReportRepository:
    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    async def record(self, report: InsightsReport) -> None:
        """Upsert the report for its date (re-running the same day overwrites in place)."""
        await self._collection.replace_one(
            {"_id": report.id}, report.model_dump(by_alias=True), upsert=True
        )

    async def get(self, date_key: str) -> InsightsReport | None:
        doc = await self._collection.find_one({"_id": date_key})
        return InsightsReport.model_validate(doc) if doc is not None else None

    async def latest(self) -> InsightsReport | None:
        docs = await self._collection.find().sort("_id", -1).limit(1).to_list(length=1)
        return InsightsReport.model_validate(docs[0]) if docs else None

    async def list_recent(self, limit: int = 30) -> list[InsightsReport]:
        docs = await self._collection.find().sort("_id", -1).limit(limit).to_list(length=limit)
        return [InsightsReport.model_validate(doc) for doc in docs]
