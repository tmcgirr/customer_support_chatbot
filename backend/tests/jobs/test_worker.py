"""Worker tests: a claimed job runs through dispatch to done; a handler failure
retries/dead-letters. Uses the real Worker against a test MongoDB."""

import logging
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import get_settings
from app.domain.conversations.repository import ConversationRepository
from app.domain.jobs.repository import JobRepository
from app.worker import Worker
from tests.jobs.conftest import Database


def _worker(db: Database) -> Worker:
    return Worker(db, settings=get_settings())


async def test_monitor_emits_critical_alert_for_dead_letter(
    db: Database, caplog: pytest.LogCaptureFixture
) -> None:
    await db["jobs"].insert_one(
        {
            "_id": "j_dl",
            "type": "deliver_request",
            "status": "dead_letter",
            "attempts": 5,
            "max_attempts": 5,
            "available_at": datetime.now(UTC),
            "created_at": datetime.now(UTC),
        }
    )
    worker = _worker(db)
    with caplog.at_level(logging.ERROR):
        await worker._monitor()
    alerts = [r for r in caplog.records if r.getMessage() == "worker.alert"]
    assert alerts, "expected a worker.alert log for the dead-lettered job"
    assert getattr(alerts[0], "context", {}).get("alert") == "dead_letter_jobs"


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


async def test_worker_delivers_a_request(db: Database) -> None:
    # The deliver_request handler routes through DeliveryService + the (simulated)
    # client, marking the request delivered with a synthetic external reference.
    from datetime import UTC, datetime

    from app.core import ids
    from app.domain.requests.models import Contact, RequestRecord
    from app.domain.requests.repository import RequestRepository

    requests = RequestRepository(db["requests"])
    record = RequestRecord(
        id=ids.request_id(),
        type="strategy_call",
        conversation_id="cnv_1",
        idempotency_key="k1",
        reference="REF-WORKER",
        contact=Contact(email="a@b.com"),
        consent_version="c",
        created_at=datetime.now(UTC),
    )
    await db["requests"].insert_one(record.model_dump(by_alias=True))
    jobs = JobRepository(db["jobs"])
    await jobs.enqueue("deliver_request", resource_id=record.id)

    worker = _worker(db)
    claimed = await jobs.claim(worker._owner, lease_seconds=60)  # noqa: SLF001
    assert claimed is not None
    await worker._run_job(claimed)  # noqa: SLF001

    stored = await requests.get(record.id)
    assert stored is not None and stored.status == "delivered"
    assert stored.external_reference == "sim-REF-WORKER"


async def test_worker_deadletter_parks_the_request(db: Database) -> None:
    # An unexpected (non-DeliveryError) failure that exhausts retries dead-letters
    # the job; the worker must reconcile the request to delivery_failed (not leave
    # it stuck in 'delivering').
    from datetime import UTC, datetime

    from app.core import ids
    from app.domain.requests.models import Contact, RequestRecord
    from app.domain.requests.repository import RequestRepository

    class _BoomClient:
        async def deliver(self, record: object) -> object:
            raise RuntimeError("boom")

        async def find_by_reference(self, reference: str) -> str | None:
            return None

    requests = RequestRepository(db["requests"])
    record = RequestRecord(
        id=ids.request_id(),
        type="strategy_call",
        conversation_id="cnv_1",
        idempotency_key="k1",
        reference="REF-DL",
        contact=Contact(email="a@b.com"),
        consent_version="c",
        created_at=datetime.now(UTC),
    )
    await db["requests"].insert_one(record.model_dump(by_alias=True))
    jobs = JobRepository(db["jobs"])
    job = await jobs.enqueue("deliver_request", resource_id=record.id, max_attempts=1)

    worker = Worker(db, settings=get_settings(), delivery_client=_BoomClient())  # type: ignore[arg-type]
    claimed = await jobs.claim(worker._owner, lease_seconds=60)  # noqa: SLF001
    assert claimed is not None
    await worker._run_job(claimed)  # noqa: SLF001

    job_doc = await db["jobs"].find_one({"_id": job.id})
    assert job_doc is not None and job_doc["status"] == "dead_letter"
    stored = await requests.get(record.id)
    assert stored is not None and stored.status == "delivery_failed"
    assert stored.last_delivery_error == "delivery_dead_letter"


async def test_worker_polls_indexing_to_indexed(db: Database) -> None:
    # poll_indexing dispatches to the handler; the simulated store reports the file
    # indexed, so the job completes and the source's status is updated.
    from app.domain.knowledge.repository import KnowledgeSourceRepository
    from app.domain.knowledge.store import SimulatedKnowledgeStore

    knowledge = KnowledgeSourceRepository(db["knowledge_sources"])
    await knowledge.record_source(
        source_id="kbs_1",
        openai_file_id="file_1",
        vector_store_id="vs",
        title="Doc",
        category="general",
        approved=True,
        lifecycle="active",
        indexing_status="pending",
    )
    jobs = JobRepository(db["jobs"])
    job = await jobs.enqueue("poll_indexing", resource_id="kbs_1")

    worker = Worker(db, settings=get_settings(), knowledge_store=SimulatedKnowledgeStore())
    claimed = await jobs.claim(worker._owner, lease_seconds=60)  # noqa: SLF001
    assert claimed is not None
    await worker._run_job(claimed)  # noqa: SLF001

    doc = await db["jobs"].find_one({"_id": job.id})
    assert doc is not None and doc["status"] == "done"
    source = await knowledge.get("kbs_1")
    assert source is not None and source.indexing_status == "indexed"


async def test_worker_deadletter_marks_indexing_failed(db: Database) -> None:
    # A poll_indexing job that exhausts its budget (store keeps erroring) must dead-letter
    # AND reconcile the source's status to 'failed' — not leave it stuck at 'pending'
    # showing a perpetual "Indexing…" in the admin UI.
    from app.domain.knowledge.repository import KnowledgeSourceRepository
    from app.domain.knowledge.store import IndexingStatus, KnowledgeStoreError

    class _StuckStore:
        channel = "stuck"

        async def upload(self, *, filename: str, content: bytes) -> str:
            raise AssertionError("unused")

        async def attach(self, file_id: str, *, attributes: dict[str, str]) -> IndexingStatus:
            raise AssertionError("unused")

        async def status(self, file_id: str) -> IndexingStatus:
            raise KnowledgeStoreError("still_failing", retryable=True)

        async def detach(self, file_id: str) -> None:
            raise AssertionError("unused")

    knowledge = KnowledgeSourceRepository(db["knowledge_sources"])
    await knowledge.record_source(
        source_id="kbs_dl",
        openai_file_id="file_dl",
        vector_store_id="vs",
        title="Doc",
        category="general",
        approved=True,
        lifecycle="active",
        indexing_status="pending",
    )
    jobs = JobRepository(db["jobs"])
    job = await jobs.enqueue("poll_indexing", resource_id="kbs_dl", max_attempts=1)

    worker = Worker(db, settings=get_settings(), knowledge_store=_StuckStore())  # type: ignore[arg-type]
    claimed = await jobs.claim(worker._owner, lease_seconds=60)  # noqa: SLF001
    assert claimed is not None
    await worker._run_job(claimed)  # noqa: SLF001

    job_doc = await db["jobs"].find_one({"_id": job.id})
    assert job_doc is not None and job_doc["status"] == "dead_letter"
    source = await knowledge.get("kbs_dl")
    assert source is not None and source.indexing_status == "failed"
