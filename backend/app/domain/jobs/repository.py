"""Job queue repository (contracts §7 claim, §8 indexes).

The claim is a single atomic ``find_one_and_update`` — exactly one worker can
transition a pending job to running, mirroring the conversation turn lock. A
lease (`lock_expires_at`) makes a crashed worker's job reclaimable. ``attempts``
increments on every claim, so a job that keeps crashing mid-run still exhausts
its budget and dead-letters rather than looping forever.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ASCENDING, ReturnDocument

from app.core import ids
from app.domain.jobs.models import Job, JobStatus, JobType

Collection = AsyncIOMotorCollection[dict[str, Any]]

# Job types that are periodic singletons — the scheduler keeps at most one active
# (pending/running) at a time via has_active().
_ACTIVE_STATUSES = ("pending", "running")


def _now() -> datetime:
    return datetime.now(UTC)


# Terminal jobs (done / dead_letter) are pruned this long after they finish so the
# collection doesn't grow without bound (a TTL index on ``terminal_at``).
_TERMINAL_TTL_SECONDS = 7 * 86_400


async def ensure_indexes(collection: Collection) -> None:
    """Contracts §8: the claim index and the lease-expiry index (plus a type index
    for the scheduler's dedup check and a TTL that reaps terminal jobs)."""
    await collection.create_index(
        [("status", ASCENDING), ("available_at", ASCENDING)], name="status_available"
    )
    await collection.create_index(
        [("lock_expires_at", ASCENDING)], name="lock_expires", sparse=True
    )
    await collection.create_index([("type", ASCENDING), ("status", ASCENDING)], name="type_status")
    await collection.create_index(
        [("resource_id", ASCENDING), ("type", ASCENDING)], name="resource_type", sparse=True
    )
    await collection.create_index(
        [("terminal_at", ASCENDING)],
        name="terminal_ttl",
        expireAfterSeconds=_TERMINAL_TTL_SECONDS,
        sparse=True,
    )


class JobRepository:
    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    async def enqueue(
        self,
        job_type: JobType,
        *,
        resource_id: str | None = None,
        max_attempts: int = 5,
        available_at: datetime | None = None,
    ) -> Job:
        now = _now()
        job = Job(
            id=ids.job_id(),
            type=job_type,
            resource_id=resource_id,
            status="pending",
            attempts=0,
            max_attempts=max_attempts,
            available_at=available_at or now,
            created_at=now,
        )
        await self._collection.insert_one(job.model_dump(by_alias=True))
        return job

    async def has_active(self, job_type: JobType) -> bool:
        """Whether a pending/running job of this type exists (scheduler dedup)."""
        doc = await self._collection.find_one(
            {"type": job_type, "status": {"$in": list(_ACTIVE_STATUSES)}}
        )
        return doc is not None

    async def has_active_for_resource(self, job_type: JobType, resource_id: str) -> bool:
        """Whether a pending/running job of this type targets ``resource_id`` — the
        delivery reconciliation sweep uses this to avoid touching in-flight requests."""
        doc = await self._collection.find_one(
            {
                "type": job_type,
                "resource_id": resource_id,
                "status": {"$in": list(_ACTIVE_STATUSES)},
            }
        )
        return doc is not None

    async def claim(self, lock_owner: str, *, lease_seconds: int) -> Job | None:
        """Atomically claim the oldest-due pending job (contracts §7).

        Exactly one caller can transition a given job pending→running. Increments
        attempts and stamps a lease so a crash can be reclaimed. Returns None when
        nothing is due.
        """
        now = _now()
        result = await self._collection.find_one_and_update(
            {"status": "pending", "available_at": {"$lte": now}},
            {
                "$set": {
                    "status": "running",
                    "lock_owner": lock_owner,
                    "lock_expires_at": now + timedelta(seconds=lease_seconds),
                },
                "$inc": {"attempts": 1},
            },
            sort=[("available_at", ASCENDING)],
            return_document=ReturnDocument.AFTER,
        )
        return Job.model_validate(result) if result is not None else None

    async def complete(self, job_id: str, lock_owner: str) -> bool:
        """Mark done — but ONLY if this worker still owns the running job. If the
        lease was reclaimed by another worker, the write no-ops (returns False) so
        a slow worker can't clobber the reclaimer's result."""
        result = await self._collection.update_one(
            {"_id": job_id, "lock_owner": lock_owner, "status": "running"},
            {
                "$set": {
                    "status": "done",
                    "terminal_at": _now(),
                    "lock_owner": None,
                    "lock_expires_at": None,
                }
            },
        )
        return result.modified_count > 0

    async def fail(self, job: Job, *, error_code: str, backoff_seconds: float) -> JobStatus | None:
        """Record a handler failure: retry with backoff, or dead-letter once the
        attempt budget is spent. Guarded on ownership — returns None (lease lost) if
        the job was reclaimed, so a stale worker can't resurrect/clobber it."""
        guard = {"_id": job.id, "lock_owner": job.lock_owner, "status": "running"}
        if job.attempts >= job.max_attempts:
            result = await self._collection.update_one(
                guard,
                {
                    "$set": {
                        "status": "dead_letter",
                        "last_error": error_code,
                        "terminal_at": _now(),
                        "lock_owner": None,
                        "lock_expires_at": None,
                    }
                },
            )
            return "dead_letter" if result.modified_count else None
        result = await self._collection.update_one(
            guard,
            {
                "$set": {
                    "status": "pending",
                    "available_at": _now() + timedelta(seconds=backoff_seconds),
                    "last_error": error_code,
                    "lock_owner": None,
                    "lock_expires_at": None,
                }
            },
        )
        return "pending" if result.modified_count else None

    async def reclaim_expired(self) -> list[Job]:
        """Recover jobs whose lease expired (worker hard-crashed mid-run). Ones that
        have already spent their attempt budget dead-letter (poison-pill guard — they
        crashed the worker before fail() could run); the rest go back to pending.

        Returns the jobs that were dead-lettered here, so the caller can run their
        type-specific reconciliation hook (e.g. park a request / fail an erasure) —
        this route bypasses fail(), so without it a resource would be stuck silently."""
        now = _now()
        expired = {"status": "running", "lock_expires_at": {"$lt": now}}
        # Snapshot the budget-exhausted expired jobs BEFORE mutating so we can return
        # them for hook processing (the update strips the fields we'd match on).
        dead_docs = await self._collection.find(
            {**expired, "$expr": {"$gte": ["$attempts", "$max_attempts"]}}
        ).to_list(length=None)
        dead_jobs = [Job.model_validate(d) for d in dead_docs]
        if dead_jobs:
            # Budget-exhausted crash loops → dead-letter instead of looping forever.
            await self._collection.update_many(
                {"_id": {"$in": [j.id for j in dead_jobs]}, **expired},
                {
                    "$set": {
                        "status": "dead_letter",
                        "last_error": "lease_expired",
                        "terminal_at": now,
                        "lock_owner": None,
                        "lock_expires_at": None,
                    }
                },
            )
        # The rest of the expired-lease jobs go back to pending for another attempt.
        await self._collection.update_many(
            expired,
            {"$set": {"status": "pending", "lock_owner": None, "lock_expires_at": None}},
        )
        return dead_jobs

    async def counts(self) -> dict[str, int]:
        """Status → count, for monitoring (queue depth, dead-letter count)."""
        cursor = self._collection.aggregate([{"$group": {"_id": "$status", "count": {"$sum": 1}}}])
        return {str(doc["_id"]): int(doc["count"]) for doc in await cursor.to_list(length=None)}
