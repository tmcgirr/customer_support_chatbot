"""Real delivery transports + the ENV-selected factory (V1.5).

Each adapter implements the ``DeliveryClient`` Protocol behind the delivery
boundary (invariant #4/#11): provider libraries (httpx, smtplib), their types,
and their errors NEVER leave this module — every failure is normalized to a
``DeliveryError`` with a ``retryable`` flag, and success returns a neutral
``DeliveryResult``.

Webhooks and SMTP relays cannot be de-duplicated (Slack/Teams ignore custom
headers; inboxes don't dedupe), and their ``find_by_reference`` probe can't query
them, so the ONLY defence against a double-send is classification: a failure is
marked ``retryable`` ONLY when we are certain nothing was delivered — a pre-send
connection failure, or an explicit "not processed" status (HTTP 429/503). Any
outcome that might have partially delivered is PARKED (``retryable=False``) for
an admin to resolve, never blind-retried.
"""

import asyncio
import contextlib
import smtplib
from email.message import EmailMessage

import httpx

from app.core.config import Settings
from app.core.logging import get_logger
from app.domain.delivery.client import (
    DeliveryClient,
    DeliveryError,
    DeliveryResult,
    SimulatedDeliveryClient,
)
from app.domain.delivery.message import format_request
from app.domain.requests.models import RequestRecord

logger = get_logger("app.delivery.adapters")


class WebhookDeliveryClient:
    """POST the request to any inbound webhook — a Slack/Teams incoming webhook, a
    Zapier catch hook, or a CRM intake endpoint. Slack/Teams accept a ``{"text": …}``
    body, which we send alongside structured fields so richer receivers can use them."""

    channel = "webhook"

    def __init__(self, url: str, *, timeout: float = 10.0) -> None:
        self._url = url
        self._timeout = timeout

    async def deliver(self, record: RequestRecord) -> DeliveryResult:
        message = format_request(record)
        payload = {
            "text": message.to_text(),
            "reference": record.reference,
            "type": record.type,
            "fields": message.as_dict(),
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._url, json=payload, headers={"Idempotency-Key": record.reference}
                )
        except (httpx.ConnectError, httpx.ConnectTimeout):
            # The connection was never established → nothing was sent → safe to retry.
            raise DeliveryError("webhook_unreachable", retryable=True) from None
        except httpx.HTTPError:
            # Any OTHER transport error (read/write timeout, protocol) can happen after the
            # request bytes were sent. A webhook can't be de-duplicated, so a retry might
            # double-post — treat as ambiguous and PARK for admin (invariant #11).
            raise DeliveryError("webhook_ambiguous", retryable=False) from None
        except Exception:
            # e.g. httpx.InvalidURL (a bad configured URL) — a permanent config error.
            # Catch broadly so no provider exception type escapes the boundary (#4).
            raise DeliveryError("webhook_bad_request", retryable=False) from None
        status = resp.status_code
        if 200 <= status < 300:
            return DeliveryResult(external_reference=f"webhook-{record.reference}")
        if status in (429, 503):
            # Explicitly rate-limited / unavailable — the message was NOT processed, so a
            # backoff retry is safe (no duplicate).
            raise DeliveryError("webhook_rate_limited", retryable=True)
        # 3xx (httpx does not follow redirects → nothing delivered), other 4xx (bad
        # url/auth), other 5xx (server got it, outcome ambiguous): never blind-retry an
        # un-dedupable channel — park for admin.
        raise DeliveryError("webhook_rejected", retryable=False)

    async def find_by_reference(self, reference: str) -> str | None:
        # A fire-and-forget webhook can't be queried, so the probe reports "unknown".
        # Safety comes from deliver() never marking a post-send failure retryable.
        return None


class EmailDeliveryClient:
    """Send the request as an email to a team inbox via an SMTP relay. Uses stdlib
    smtplib in a worker thread (no extra dependency, non-blocking on the event loop)."""

    channel = "email"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        sender: str,
        recipient: str,
        use_tls: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._sender = sender
        self._recipient = recipient
        self._use_tls = use_tls

    async def deliver(self, record: RequestRecord) -> DeliveryResult:
        message = format_request(record)
        email = EmailMessage()
        email["Subject"] = message.title
        email["From"] = self._sender
        email["To"] = self._recipient
        email["X-Request-Reference"] = record.reference  # trace header
        email.set_content(message.to_text())
        # _send raises a fully-classified DeliveryError; nothing else escapes it.
        await asyncio.to_thread(self._send, email)
        return DeliveryResult(external_reference=f"email-{record.reference}")

    def _send(self, email: EmailMessage) -> None:
        try:
            server = smtplib.SMTP(self._host, self._port, timeout=15)
        except (OSError, smtplib.SMTPConnectError):
            # Never connected → nothing was sent → safe to retry.
            raise DeliveryError("email_unreachable", retryable=True) from None
        try:
            try:
                if self._use_tls:
                    server.starttls()
                if self._user:
                    server.login(self._user, self._password)
            except smtplib.SMTPAuthenticationError:
                raise DeliveryError("email_auth_failed", retryable=False) from None
            except (smtplib.SMTPException, OSError):
                # TLS/login failed BEFORE the message was sent → safe to retry.
                raise DeliveryError("email_setup_failed", retryable=True) from None
            try:
                server.send_message(email)
            except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused):
                # Bad from/to — won't fix on retry.
                raise DeliveryError("email_rejected", retryable=False) from None
            except (smtplib.SMTPException, OSError):
                # A failure DURING send is ambiguous (the relay may have accepted it) —
                # park rather than risk a duplicate email (invariant #11).
                raise DeliveryError("email_ambiguous", retryable=False) from None
        except DeliveryError:
            raise
        except Exception:
            # Guarantee no smtplib/other provider type escapes the boundary (#4).
            raise DeliveryError("email_error", retryable=False) from None
        finally:
            with contextlib.suppress(Exception):
                server.quit()

    async def find_by_reference(self, reference: str) -> str | None:
        return None  # SMTP can't be queried; safety is in deliver()'s classification.


def build_delivery_client(settings: Settings) -> DeliveryClient:
    """Select the delivery transport from config. Falls back to the simulated mock
    (and logs a warning) when the chosen transport is missing required config — so the
    wiring is always present and switching a real destination on is a config change."""
    transport = settings.delivery_transport
    if transport == "webhook":
        url = settings.delivery_webhook_url.get_secret_value().strip()
        if url:
            return WebhookDeliveryClient(url, timeout=settings.delivery_webhook_timeout_seconds)
        logger.warning(
            "delivery.transport_unconfigured", extra={"context": {"transport": "webhook"}}
        )
    elif transport == "email":
        if (
            settings.delivery_email_smtp_host.strip()
            and settings.delivery_email_from.strip()
            and settings.delivery_email_to.strip()
        ):
            return EmailDeliveryClient(
                host=settings.delivery_email_smtp_host,
                port=settings.delivery_email_smtp_port,
                user=settings.delivery_email_smtp_user,
                password=settings.delivery_email_smtp_password.get_secret_value(),
                sender=settings.delivery_email_from,
                recipient=settings.delivery_email_to,
                use_tls=settings.delivery_email_use_tls,
            )
        logger.warning("delivery.transport_unconfigured", extra={"context": {"transport": "email"}})
    return SimulatedDeliveryClient()
