"""Delivery service — runs on the worker via the ``deliver_request`` job.

Delivers a persisted request to its destination exactly once (CLAUDE.md
invariant #11): on a retry it first asks the destination whether the request's
reference was already delivered (never a blind re-send), and an ambiguous or
exhausted outcome is PARKED as ``delivery_failed`` for admin action — never a
re-prompt to the user. Drives request status received → delivering →
delivered / delivery_failed.
"""

from app.core.logging import get_logger
from app.domain.delivery.client import DeliveryClient, DeliveryError
from app.domain.requests.models import Destination, RequestType
from app.domain.requests.repository import RequestRepository

logger = get_logger("app.delivery.service")

# Category routing (doc 06 §6): strategy calls → CRM/scheduler; support + escalation
# → ticketing. Labels are placeholders until real destinations are selected.
_DESTINATION: dict[RequestType, Destination] = {
    "strategy_call": "hubspot",
    "portal_support": "zendesk",
    "human_escalation": "zendesk",
}


class DeliveryService:
    def __init__(self, requests: RequestRepository, client: DeliveryClient) -> None:
        self._requests = requests
        self._client = client

    async def deliver(self, request_id: str, *, attempt: int, max_attempts: int) -> None:
        """Deliver one request. Raises ``DeliveryError`` ONLY to signal the worker
        to retry (transient, budget remaining); a permanent or budget-exhausted
        failure is parked as ``delivery_failed`` and returns normally."""
        record = await self._requests.get(request_id)
        if record is None:
            # The request was deleted (e.g. a privacy deletion) before delivery.
            logger.info("delivery.request_missing", extra={"context": {"request_id": request_id}})
            return
        if record.status in ("delivered", "delivery_failed"):
            # Terminal: never re-send a delivered request, and a parked failure is
            # only re-delivered by an explicit admin action (which resets status).
            return

        destination = _DESTINATION[record.type]
        await self._requests.mark_delivering(request_id, destination)

        # On a retry, never re-send blind: ask the destination if the reference is
        # already there. An ambiguous probe parks for admin rather than risking a dup.
        if attempt > 1:
            try:
                existing = await self._client.find_by_reference(record.reference)
            except DeliveryError:
                await self._requests.mark_delivery_failed(request_id, "ambiguous_delivery")
                logger.warning("delivery.ambiguous", extra={"context": {"request_id": request_id}})
                return
            if existing is not None:
                await self._requests.mark_delivered(request_id, existing)
                return

        try:
            result = await self._client.deliver(record)
        except DeliveryError as exc:
            if exc.retryable and attempt < max_attempts:
                await self._requests.record_delivery_error(request_id, exc.code)
                raise  # worker retries with backoff
            # Permanent, or retries exhausted — park for admin (invariant #11).
            await self._requests.mark_delivery_failed(request_id, exc.code)
            logger.warning(
                "delivery.failed",
                extra={
                    "context": {
                        "request_id": request_id,
                        "error_code": exc.code,
                        "attempt": attempt,
                    }
                },
            )
            return

        await self._requests.mark_delivered(request_id, result.external_reference)
        logger.info(
            "delivery.delivered",
            extra={"context": {"request_id": request_id, "destination": destination}},
        )
