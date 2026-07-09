"""Delivery provider boundary (CLAUDE.md invariant #4, #11).

External systems (CRM/scheduler, ticketing) are reached ONLY through a
``DeliveryClient``. Like the model adapter, no provider SDK type, id, or error
escapes this boundary — callers see a normalized ``DeliveryResult`` /
``DeliveryError``. Delivery happens exclusively on the worker via the
``deliver_request`` job (never the model, never the request handler inline).
"""

from dataclasses import dataclass
from typing import Protocol

from app.core.logging import get_logger
from app.domain.requests.models import RequestRecord

logger = get_logger("app.delivery")


@dataclass(frozen=True)
class DeliveryResult:
    external_reference: str  # the id the destination assigns (CRM deal / ticket id)


class DeliveryError(Exception):
    """A normalized delivery failure. ``retryable`` distinguishes a transient fault
    (retry with backoff) from a permanent one (park for admin, don't retry)."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class DeliveryClient(Protocol):
    # Transport name recorded on the request + shown in admin (simulated/webhook/email).
    channel: str

    async def deliver(self, record: RequestRecord) -> DeliveryResult:
        """Send the request to the destination; return its external reference. Raise
        ``DeliveryError`` on failure (never a provider-typed exception).

        Exactly-once is the adapter's responsibility (invariant #11): a destination
        that can dedupe should be queried by ``find_by_reference`` before a retry; a
        destination that CANNOT (webhook/email) must classify any possibly-delivered
        outcome as ``retryable=False`` so the worker parks it instead of re-sending."""
        ...

    async def find_by_reference(self, reference: str) -> str | None:
        """Idempotency probe: return the external reference if this request's local
        ``reference`` was already delivered, else None. Adapters that cannot query
        their destination return None and rely on deliver()'s classification instead."""
        ...


class SimulatedDeliveryClient:
    """Default client until real CRM/ticketing destinations are selected (doc 06 §6).

    Simulates a successful delivery with a synthetic reference — good enough to run
    the full delivery pipeline on staging. It has no external store, so the
    idempotency probe always reports "not found" (a benign no-op; the real
    idempotency behaviour is exercised in tests via a scriptable fake)."""

    channel = "simulated"

    async def deliver(self, record: RequestRecord) -> DeliveryResult:
        logger.info(
            "delivery.simulated",
            extra={"context": {"request_id": record.id, "type": record.type}},
        )
        return DeliveryResult(external_reference=f"sim-{record.reference}")

    async def find_by_reference(self, reference: str) -> str | None:
        return None
