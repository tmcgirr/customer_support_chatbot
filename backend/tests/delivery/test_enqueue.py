"""RequestService enqueues a deliver_request job exactly once on fresh create,
only when delivery is enabled (dark-launch flag)."""

from app.domain.conversations.repository import ConversationRepository
from app.domain.jobs.repository import JobRepository
from app.domain.requests.models import Contact
from app.domain.requests.repository import RequestRepository
from app.domain.requests.service import RequestService
from tests.delivery.conftest import Database

_PAYLOAD = {
    "request_type": "strategy_call",
    "conversation_id": "cnv_enqueue",
    "contact": Contact(email="a@b.com"),
    "fields": {"reason": "help with AI"},
    "consent_version": "consent-2026-07",
    "confirmed": True,
}


def _service(db: Database, *, enable_delivery: bool) -> RequestService:
    return RequestService(
        RequestRepository(db["requests"]),
        ConversationRepository(db["conversations"]),
        jobs=JobRepository(db["jobs"]),
        enable_delivery=enable_delivery,
    )


async def test_submit_enqueues_delivery_when_enabled(db: Database) -> None:
    record, _ = await _service(db, enable_delivery=True).submit(**_PAYLOAD, idempotency_key="k1")
    jobs = await db["jobs"].find({"type": "deliver_request"}).to_list(length=None)
    assert len(jobs) == 1
    assert jobs[0]["resource_id"] == record.id


async def test_submit_does_not_enqueue_when_disabled(db: Database) -> None:
    await _service(db, enable_delivery=False).submit(**_PAYLOAD, idempotency_key="k1")
    assert await db["jobs"].count_documents({"type": "deliver_request"}) == 0


async def test_submit_replay_enqueues_delivery_once(db: Database) -> None:
    service = _service(db, enable_delivery=True)
    await service.submit(**_PAYLOAD, idempotency_key="k1")
    await service.submit(**_PAYLOAD, idempotency_key="k1")  # duplicate → replay, no re-enqueue
    assert await db["jobs"].count_documents({"type": "deliver_request"}) == 1
