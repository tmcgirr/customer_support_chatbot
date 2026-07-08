"""Reconciliation sweep: rescue requests orphaned by a dead/lost delivery job."""

from datetime import UTC, datetime, timedelta

from app.domain.jobs.repository import JobRepository
from app.domain.jobs.tasks import run_reconcile_deliveries
from app.domain.requests.repository import RequestRepository
from tests.delivery.conftest import Database, make_request


async def _backdate(db: Database, request_id: str, seconds: int) -> None:
    await db["requests"].update_one(
        {"_id": request_id},
        {"$set": {"created_at": datetime.now(UTC) - timedelta(seconds=seconds)}},
    )


async def test_stuck_delivering_with_no_job_is_parked(db: Database) -> None:
    requests = RequestRepository(db["requests"])
    jobs = JobRepository(db["jobs"])
    req = await make_request(requests, status="delivering")
    await _backdate(db, req.id, 3600)  # stuck well past the threshold, no active job

    result = await run_reconcile_deliveries(
        requests, jobs, stuck_after_seconds=900, enable_delivery=True
    )
    assert result["parked"] == 1
    stored = await requests.get(req.id)
    assert stored is not None and stored.status == "delivery_failed"
    assert stored.last_delivery_error == "orphaned_delivery"


async def test_received_orphan_is_reenqueued_when_enabled(db: Database) -> None:
    requests = RequestRepository(db["requests"])
    jobs = JobRepository(db["jobs"])
    req = await make_request(requests, status="received")
    await _backdate(db, req.id, 3600)

    result = await run_reconcile_deliveries(
        requests, jobs, stuck_after_seconds=900, enable_delivery=True
    )
    assert result["reenqueued"] == 1
    assert await jobs.has_active_for_resource("deliver_request", req.id) is True


async def test_request_with_active_job_is_left_alone(db: Database) -> None:
    requests = RequestRepository(db["requests"])
    jobs = JobRepository(db["jobs"])
    req = await make_request(requests, status="delivering")
    await _backdate(db, req.id, 3600)
    await jobs.enqueue("deliver_request", resource_id=req.id)  # still in flight

    result = await run_reconcile_deliveries(
        requests, jobs, stuck_after_seconds=900, enable_delivery=True
    )
    assert result == {"parked": 0, "reenqueued": 0}
    stored = await requests.get(req.id)
    assert stored is not None and stored.status == "delivering"  # untouched


async def test_recent_request_is_not_reconciled(db: Database) -> None:
    # Freshly-created (in-flight) requests must not be reconciled prematurely.
    requests = RequestRepository(db["requests"])
    jobs = JobRepository(db["jobs"])
    await make_request(requests, status="delivering")  # created just now
    result = await run_reconcile_deliveries(
        requests, jobs, stuck_after_seconds=900, enable_delivery=True
    )
    assert result == {"parked": 0, "reenqueued": 0}
