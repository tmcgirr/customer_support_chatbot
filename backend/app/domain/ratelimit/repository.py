"""Per-IP creation rate limiter — a fixed-window counter with TTL expiry.

One document per (identifier, window); Mongo's TTL monitor purges expired
windows. The identifier is stored as a keyed HMAC, never a raw client IP, so no
PII sits at rest (contracts §10). A fixed window can allow up to ~2x the cap
across a boundary — acceptable for a coarse abuse cap, not billing-grade.
"""

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ASCENDING, ReturnDocument

Collection = AsyncIOMotorCollection[dict[str, Any]]


async def ensure_indexes(collection: Collection) -> None:
    """TTL index: Mongo deletes a window document once ``expires_at`` passes."""
    await collection.create_index(
        [("expires_at", ASCENDING)], expireAfterSeconds=0, name="window_ttl"
    )


class RateLimitRepository:
    def __init__(self, collection: Collection, *, secret: str) -> None:
        self._collection = collection
        self._secret = secret.encode("utf-8")

    def _window_key(self, identifier: str, window_start: int) -> str:
        return hmac.new(
            self._secret, f"{identifier}:{window_start}".encode(), hashlib.sha256
        ).hexdigest()

    async def hit(
        self,
        identifier: str,
        *,
        limit: int,
        window_seconds: int,
        now: datetime | None = None,
    ) -> bool:
        """Atomically increment the current window's counter for ``identifier``.

        Returns True if the request is allowed (post-increment count <= limit),
        False if the limit is exceeded. The upsert + ``$inc`` is a single atomic
        op, so concurrent creations from one IP can't undercount.
        """
        current = now or datetime.now(UTC)
        epoch = int(current.timestamp())
        window_start = epoch - (epoch % window_seconds)
        expires_at = datetime.fromtimestamp(window_start + window_seconds, tz=UTC)
        doc = await self._collection.find_one_and_update(
            {"_id": self._window_key(identifier, window_start)},
            {"$inc": {"count": 1}, "$setOnInsert": {"expires_at": expires_at}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return int(doc["count"]) <= limit
