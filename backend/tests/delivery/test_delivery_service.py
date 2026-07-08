"""DeliveryService tests: the idempotent deliver flow + status transitions."""

from app.domain.delivery.client import DeliveryError
from app.domain.delivery.service import DeliveryService
from app.domain.requests.repository import RequestRepository
from tests.delivery.conftest import Database, make_request
from tests.fakes import FakeDeliveryClient


def _service(db: Database, client: FakeDeliveryClient) -> tuple[DeliveryService, RequestRepository]:
    repo = RequestRepository(db["requests"])
    return DeliveryService(repo, client), repo


async def test_deliver_success_sets_external_reference(db: Database) -> None:
    client = FakeDeliveryClient()
    service, repo = _service(db, client)
    req = await make_request(repo)

    await service.deliver(req.id, attempt=1, max_attempts=3)

    stored = await repo.get(req.id)
    assert stored is not None
    assert stored.status == "delivered"
    assert stored.external_reference == f"ext-{req.reference}"
    assert stored.destination == "hubspot"  # strategy_call → CRM
    assert stored.delivered_at is not None


async def test_transient_error_reraises_for_retry(db: Database) -> None:
    client = FakeDeliveryClient(deliver_results=[DeliveryError("timeout", retryable=True)])
    service, repo = _service(db, client)
    req = await make_request(repo)

    # attempt 1 (< max): the service re-raises so the worker retries with backoff.
    try:
        await service.deliver(req.id, attempt=1, max_attempts=3)
        raise AssertionError("expected DeliveryError")
    except DeliveryError:
        pass
    stored = await repo.get(req.id)
    assert stored is not None and stored.status == "delivering"  # not failed yet
    assert stored.last_delivery_error == "timeout"

    # attempt 2: probe finds nothing, deliver succeeds → delivered.
    await service.deliver(req.id, attempt=2, max_attempts=3)
    stored = await repo.get(req.id)
    assert stored is not None and stored.status == "delivered"
    assert client.deliver_calls == 2 and client.find_calls == 1


async def test_permanent_error_parks_without_retry(db: Database) -> None:
    client = FakeDeliveryClient(deliver_results=[DeliveryError("bad_request", retryable=False)])
    service, repo = _service(db, client)
    req = await make_request(repo)

    await service.deliver(req.id, attempt=1, max_attempts=3)  # no raise — parked
    stored = await repo.get(req.id)
    assert stored is not None and stored.status == "delivery_failed"
    assert stored.last_delivery_error == "bad_request"


async def test_exhausted_retries_park_as_failed(db: Database) -> None:
    client = FakeDeliveryClient(deliver_results=[DeliveryError("timeout", retryable=True)])
    service, repo = _service(db, client)
    req = await make_request(repo)
    # Final attempt: retryable but budget spent → park, don't raise.
    await service.deliver(req.id, attempt=3, max_attempts=3)
    stored = await repo.get(req.id)
    assert stored is not None and stored.status == "delivery_failed"


async def test_retry_finds_existing_delivery_no_double_send(db: Database) -> None:
    # The idempotency guarantee: a prior attempt actually reached the destination;
    # the retry's probe finds it and marks delivered WITHOUT sending again.
    client = FakeDeliveryClient(existing={"REF-TEST": "ext-already"})
    service, repo = _service(db, client)
    req = await make_request(repo, reference="REF-TEST")

    await service.deliver(req.id, attempt=2, max_attempts=3)
    stored = await repo.get(req.id)
    assert stored is not None and stored.status == "delivered"
    assert stored.external_reference == "ext-already"
    assert client.deliver_calls == 0  # never re-sent


async def test_ambiguous_probe_parks_for_admin(db: Database) -> None:
    client = FakeDeliveryClient(find_raises=True)
    service, repo = _service(db, client)
    req = await make_request(repo)

    await service.deliver(req.id, attempt=2, max_attempts=3)
    stored = await repo.get(req.id)
    assert stored is not None and stored.status == "delivery_failed"
    assert stored.last_delivery_error == "ambiguous_delivery"
    assert client.deliver_calls == 0  # never blind-retried


async def test_already_delivered_is_a_noop(db: Database) -> None:
    client = FakeDeliveryClient()
    service, repo = _service(db, client)
    req = await make_request(repo, status="delivered")

    await service.deliver(req.id, attempt=1, max_attempts=3)
    assert client.deliver_calls == 0 and client.find_calls == 0


async def test_missing_request_is_a_noop(db: Database) -> None:
    client = FakeDeliveryClient()
    service, _ = _service(db, client)
    await service.deliver("req_does_not_exist", attempt=1, max_attempts=3)  # no error
    assert client.deliver_calls == 0


async def test_delivery_failed_is_terminal(db: Database) -> None:
    # A parked request is never re-delivered by a stray/re-run job (only an explicit
    # admin action, which resets status, would).
    client = FakeDeliveryClient()
    service, repo = _service(db, client)
    req = await make_request(repo, status="delivery_failed")
    await service.deliver(req.id, attempt=1, max_attempts=3)
    assert client.deliver_calls == 0 and client.find_calls == 0
