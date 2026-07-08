"""Worker tests: a claimed job runs through dispatch to done; a handler failure
retries/dead-letters. Uses the real Worker against a test MongoDB."""

from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.domain.conversations.repository import ConversationRepository
from app.domain.jobs.repository import JobRepository
from app.worker import Worker
from tests.jobs.conftest import Database


def _worker(db: Database) -> Worker:
    return Worker(db, settings=get_settings())


async def test_worker_runs_a_scheduled_job_to_done(db: Database) -> None:
    jobs = JobRepository(db["jobs"])
    conversations = ConversationRepository(db["conversations"])
    # A leaked lock for the stale_lock_sweep handler to clear.
    convo = await conversations.create()
    await db["conversations"].update_one(
        {"_id": convo.id},
        {
            "$set": {
                "active_run": {"run_id": "r", "started_at": datetime.now(UTC) - timedelta(hours=1)}
            }
        },
    )
    job = await jobs.enqueue("stale_lock_sweep")

    worker = _worker(db)
    claimed = await jobs.claim(worker._owner, lease_seconds=60)  # noqa: SLF001 (test)
    assert claimed is not None
    await worker._run_job(claimed)  # noqa: SLF001 (test drives one job directly)

    doc = await db["jobs"].find_one({"_id": job.id})
    assert doc is not None and doc["status"] == "done"
    convo_doc = await db["conversations"].find_one({"_id": convo.id})
    assert convo_doc is not None and convo_doc["active_run"] is None  # handler ran


async def test_worker_dead_letters_a_job_with_no_handler(db: Database) -> None:
    jobs = JobRepository(db["jobs"])
    # deliver_request has no handler in V3 → dispatch raises → dead-letter (max_attempts=1).
    job = await jobs.enqueue("deliver_request", resource_id="req_1", max_attempts=1)

    worker = _worker(db)
    claimed = await jobs.claim(worker._owner, lease_seconds=60)  # noqa: SLF001
    assert claimed is not None
    await worker._run_job(claimed)  # noqa: SLF001

    doc = await db["jobs"].find_one({"_id": job.id})
    assert doc is not None and doc["status"] == "dead_letter"
    assert doc["last_error"] == "RuntimeError"
