"""Job queue repository tests against a real MongoDB — the atomic claim is the
load-bearing concurrency primitive, so it gets the same scrutiny as the turn lock."""

import asyncio
from datetime import UTC, datetime, timedelta

from app.domain.jobs.repository import JobRepository
from tests.jobs.conftest import Database


def _repo(db: Database) -> JobRepository:
    return JobRepository(db["jobs"])


async def test_claim_is_exactly_once_under_concurrency(db: Database) -> None:
    repo = _repo(db)
    await repo.enqueue("daily_aggregates")
    # Two workers race for the single pending job.
    a, b = await asyncio.gather(
        repo.claim("worker-a", lease_seconds=60),
        repo.claim("worker-b", lease_seconds=60),
    )
    claimed = [j for j in (a, b) if j is not None]
    assert len(claimed) == 1  # exactly one worker got it
    assert claimed[0].status == "running"
    assert claimed[0].attempts == 1


async def test_claim_drains_then_returns_none(db: Database) -> None:
    repo = _repo(db)
    for _ in range(3):
        await repo.enqueue("stale_lock_sweep")
    claimed = [await repo.claim("w", lease_seconds=60) for _ in range(3)]
    assert all(j is not None for j in claimed)
    assert await repo.claim("w", lease_seconds=60) is None  # nothing left


async def test_future_available_at_is_not_claimed(db: Database) -> None:
    repo = _repo(db)
    await repo.enqueue("daily_aggregates", available_at=datetime.now(UTC) + timedelta(hours=1))
    assert await repo.claim("w", lease_seconds=60) is None  # not yet due


async def test_fail_retries_then_dead_letters(db: Database) -> None:
    repo = _repo(db)
    await repo.enqueue("deliver_request", resource_id="req_1", max_attempts=2)

    job1 = await repo.claim("w", lease_seconds=60)
    assert job1 is not None and job1.attempts == 1
    assert await repo.fail(job1, error_code="BoomError", backoff_seconds=0) == "pending"

    job2 = await repo.claim("w", lease_seconds=60)
    assert job2 is not None and job2.attempts == 2
    assert await repo.fail(job2, error_code="BoomError", backoff_seconds=0) == "dead_letter"

    doc = await db["jobs"].find_one({"_id": job2.id})
    assert doc is not None and doc["status"] == "dead_letter" and doc["last_error"] == "BoomError"


async def test_reclaim_expired_lease_returns_job_to_pending(db: Database) -> None:
    repo = _repo(db)
    job = await repo.enqueue("stale_lock_sweep")
    # Simulate a worker that claimed then crashed: running with an expired lease.
    await db["jobs"].update_one(
        {"_id": job.id},
        {
            "$set": {
                "status": "running",
                "lock_expires_at": datetime.now(UTC) - timedelta(minutes=1),
            }
        },
    )
    assert await repo.reclaim_expired() == 1
    reclaimed = await repo.claim("w", lease_seconds=60)
    assert reclaimed is not None and reclaimed.id == job.id


async def test_has_active_and_counts(db: Database) -> None:
    repo = _repo(db)
    assert await repo.has_active("daily_aggregates") is False
    await repo.enqueue("daily_aggregates")
    assert await repo.has_active("daily_aggregates") is True  # pending counts as active
    claimed = await repo.claim("w", lease_seconds=60)
    assert claimed is not None
    assert await repo.complete(claimed.id, "w") is True
    assert await repo.has_active("daily_aggregates") is False  # done does not
    counts = await repo.counts()
    assert counts.get("done") == 1


async def test_complete_and_fail_require_ownership(db: Database) -> None:
    # H2 guard: a worker whose lease was reclaimed can't clobber the job.
    repo = _repo(db)
    await repo.enqueue("daily_aggregates")
    job = await repo.claim("worker-a", lease_seconds=60)
    assert job is not None
    assert await repo.complete(job.id, "worker-b") is False  # not the owner → no-op
    doc = await db["jobs"].find_one({"_id": job.id})
    assert doc is not None and doc["status"] == "running"  # untouched
    assert await repo.complete(job.id, "worker-a") is True  # rightful owner


async def test_fail_after_reclaim_is_a_no_op(db: Database) -> None:
    repo = _repo(db)
    await repo.enqueue("deliver_request", resource_id="req_1", max_attempts=5)
    job = await repo.claim("worker-a", lease_seconds=60)
    assert job is not None
    # Another worker reclaimed + re-owns it while worker-a was still running.
    await db["jobs"].update_one({"_id": job.id}, {"$set": {"lock_owner": "worker-b"}})
    assert await repo.fail(job, error_code="Boom", backoff_seconds=0) is None  # lease lost
    doc = await db["jobs"].find_one({"_id": job.id})
    assert doc is not None and doc["status"] == "running" and doc["lock_owner"] == "worker-b"


async def test_reclaim_dead_letters_budget_exhausted_crash_loop(db: Database) -> None:
    # H1 poison-pill guard: a job that hard-crashed the worker after spending its
    # budget dead-letters on reclaim instead of looping forever.
    repo = _repo(db)
    job = await repo.enqueue("deliver_request", resource_id="req_1", max_attempts=2)
    await db["jobs"].update_one(
        {"_id": job.id},
        {
            "$set": {
                "status": "running",
                "attempts": 2,
                "lock_expires_at": datetime.now(UTC) - timedelta(minutes=1),
            }
        },
    )
    await repo.reclaim_expired()
    doc = await db["jobs"].find_one({"_id": job.id})
    assert doc is not None and doc["status"] == "dead_letter"
    assert doc["last_error"] == "lease_expired"
