"""LLM usage rollup repository — ``$inc`` daily upserts keyed by (date, provider, model,
category). Count-only, no PII (invariant #5); outside the retention sweep (matches aggregates)."""

from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ASCENDING

from app.domain.usage.pricing import infer_provider

Collection = AsyncIOMotorCollection[dict[str, Any]]


async def ensure_indexes(collection: Collection) -> None:
    await collection.create_index([("date", ASCENDING)], name="date")


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


class LlmUsageRepository:
    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    async def record(
        self, model: str, category: str, input_tokens: int, output_tokens: int
    ) -> None:
        """Accumulate one LLM call into today's (provider, model, category) rollup row. This is
        the adapter's ``on_usage`` hook — positional to match ``UsageHook``. Provider is inferred
        from the model id (so a fallback / embedding model is attributed correctly)."""
        provider = infer_provider(model)
        date = _today()
        await self._collection.update_one(
            {"_id": f"{date}:{provider}:{model}:{category}"},
            {
                "$inc": {
                    "input_tokens": int(input_tokens),
                    "output_tokens": int(output_tokens),
                    "requests": 1,
                },
                "$setOnInsert": {
                    "date": date,
                    "provider": provider,
                    "model": model,
                    "category": category,
                },
            },
            upsert=True,
        )

    async def rows_since(self, date_key: str) -> list[dict[str, Any]]:
        """All rollup rows on/after ``date_key`` (a ``YYYY-MM-DD`` string)."""
        return await self._collection.find({"date": {"$gte": date_key}}).to_list(length=None)
