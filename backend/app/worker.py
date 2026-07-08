"""Dedicated background worker (V1).

    uv run python -m app.worker

A single loop that (1) reclaims jobs whose lease expired, (2) enqueues due
periodic jobs, and (3) claims and runs pending jobs, dispatching by type to a
handler. Handlers are idempotent; a failure retries with exponential backoff and
dead-letters once the attempt budget is spent. Runs as its own process, sharing
the repositories with the API — no duplicated data access (CLAUDE.md).
"""

import asyncio
import contextlib
import signal
import time
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core import ids
from app.core.config import Settings, get_settings
from app.core.db import create_mongo_client, get_database
from app.core.logging import configure_logging, get_logger
from app.domain.aggregates.repository import AggregatesRepository
from app.domain.conversations.repository import ConversationRepository
from app.domain.feedback.repository import FeedbackRepository
from app.domain.jobs.models import Job, JobType
from app.domain.jobs.repository import JobRepository
from app.domain.jobs.repository import ensure_indexes as ensure_job_indexes
from app.domain.jobs.tasks import (
    run_abandonment_sweep,
    run_daily_aggregates,
    run_knowledge_review_reminder,
    run_stale_lock_sweep,
)
from app.domain.knowledge.repository import KnowledgeSourceRepository
from app.domain.requests.repository import RequestRepository

logger = get_logger("app.worker")

Database = AsyncIOMotorDatabase[dict[str, Any]]

# Periodic job cadences (seconds). The scheduler enqueues one per cadence, deduped
# so at most one of each type is ever pending/running.
_SCHEDULE: dict[JobType, int] = {
    "stale_lock_sweep": 300,
    "abandonment_sweep": 3600,
    "daily_aggregates": 86_400,
    "knowledge_review_reminder": 86_400,
}
_MONITOR_SECONDS = 60  # cadence for logging queue depth / dead-letter count
_MAX_DRAIN_PER_TICK = 20  # jobs to run per loop iteration before re-scheduling


class Worker:
    def __init__(self, db: Database, *, settings: Settings) -> None:
        self._jobs = JobRepository(db["jobs"])
        self._conversations = ConversationRepository(db["conversations"])
        self._requests = RequestRepository(db["requests"])
        self._feedback = FeedbackRepository(db["feedback"])
        self._knowledge = KnowledgeSourceRepository(db["knowledge_sources"])
        self._aggregates = AggregatesRepository(db["aggregates"])
        self._settings = settings
        self._owner = ids.prefixed_id("wrk")
        self._stop = asyncio.Event()
        self._last_scheduled: dict[JobType, float] = {}
        self._last_monitor = 0.0

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        logger.info("worker.started", extra={"context": {"owner": self._owner}})
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:
                # A tick failure must never kill the worker loop.
                logger.error("worker.tick_error", exc_info=True)
            await self._sleep(self._settings.worker_poll_seconds)
        logger.info("worker.stopped", extra={"context": {"owner": self._owner}})

    async def _sleep(self, seconds: float) -> None:
        """Sleep, but wake immediately on shutdown."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)

    async def _tick(self) -> None:
        await self._jobs.reclaim_expired()
        await self._schedule_due()
        await self._monitor()
        for _ in range(_MAX_DRAIN_PER_TICK):
            if self._stop.is_set():
                break
            job = await self._jobs.claim(
                self._owner, lease_seconds=self._settings.worker_lease_seconds
            )
            if job is None:
                break
            await self._run_job(job)

    async def _schedule_due(self) -> None:
        now = time.monotonic()
        for job_type, cadence in _SCHEDULE.items():
            last = self._last_scheduled.get(job_type)
            if last is not None and now - last < cadence:
                continue
            self._last_scheduled[job_type] = now
            # Singleton: never pile up if the previous one is still pending/running.
            if not await self._jobs.has_active(job_type):
                await self._jobs.enqueue(job_type)

    async def _monitor(self) -> None:
        now = time.monotonic()
        if now - self._last_monitor < _MONITOR_SECONDS:
            return
        self._last_monitor = now
        counts = await self._jobs.counts()
        logger.info("worker.queue", extra={"context": {"counts": counts}})

    async def _run_job(self, job: Job) -> None:
        assert job.lock_owner is not None  # set by claim()
        try:
            # Hard timeout < lease: a hung handler can't wedge the loop or outlive
            # its lease (which would let another worker double-run it).
            await asyncio.wait_for(
                self._dispatch(job), timeout=self._settings.worker_job_timeout_seconds
            )
        except Exception as exc:
            backoff = self._settings.job_backoff_base_seconds * (2 ** (job.attempts - 1))
            status = await self._jobs.fail(
                job, error_code=type(exc).__name__, backoff_seconds=backoff
            )
            if status is None:
                # Lease was reclaimed by another worker while we ran — don't clobber.
                logger.info(
                    "worker.job.lease_lost",
                    extra={"context": {"job_type": job.type, "job_id": job.id}},
                )
            else:
                logger.warning(
                    "worker.job.failed",
                    exc_info=True,
                    extra={
                        "context": {
                            "job_type": job.type,
                            "job_id": job.id,
                            "status": status,
                            "attempts": job.attempts,
                        }
                    },
                )
            return
        if await self._jobs.complete(job.id, job.lock_owner):
            logger.info(
                "worker.job.done", extra={"context": {"job_type": job.type, "job_id": job.id}}
            )
        else:
            logger.info(
                "worker.job.lease_lost",
                extra={"context": {"job_type": job.type, "job_id": job.id}},
            )

    async def _dispatch(self, job: Job) -> None:
        job_type = job.type
        if job_type == "stale_lock_sweep":
            await run_stale_lock_sweep(self._conversations, self._settings.lock_stale_seconds)
        elif job_type == "abandonment_sweep":
            await run_abandonment_sweep(
                self._conversations, self._settings.conversation_abandon_seconds
            )
        elif job_type == "knowledge_review_reminder":
            due = await run_knowledge_review_reminder(self._knowledge)
            if due:
                logger.info("worker.review_due", extra={"context": {"count": len(due)}})
        elif job_type == "daily_aggregates":
            await run_daily_aggregates(
                self._conversations, self._requests, self._feedback, self._aggregates
            )
        else:
            # deliver_request / poll_indexing / retention_sweep land in later phases.
            raise RuntimeError(f"no handler registered for job type {job_type!r}")


async def _amain() -> None:
    configure_logging()
    settings = get_settings()
    client = create_mongo_client()
    db = get_database(client)
    await ensure_job_indexes(db["jobs"])
    worker = Worker(db, settings=settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop)
    try:
        await worker.run()
    finally:
        client.close()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
