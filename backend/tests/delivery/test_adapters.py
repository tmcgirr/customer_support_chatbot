"""Delivery transports (V1.5): the neutral formatter, the webhook + email adapters
(provider libs mocked at the boundary — never a real network call), and the
ENV-selected factory with its fall-back-to-simulated behavior."""

import smtplib
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.domain.delivery.adapters import (
    EmailDeliveryClient,
    WebhookDeliveryClient,
    build_delivery_client,
)
from app.domain.delivery.client import DeliveryError
from app.domain.delivery.message import format_request
from app.domain.requests.models import Contact, RequestRecord


def _record() -> RequestRecord:
    return RequestRecord(
        id="req_1",
        type="strategy_call",
        conversation_id="cnv_1",
        idempotency_key="key_1",
        reference="REF-1",
        contact=Contact(name="Ada", email="ada@acme.com", company="Acme"),
        fields={"reason": "exploring AI", "industry": "fintech"},
        consent_version="c",
        created_at=datetime.now(UTC),
    )


# --- Formatter ---


def test_format_request_includes_contact_fields_and_reference() -> None:
    msg = format_request(_record())
    assert "REF-1" in msg.title and "strategy-call" in msg.title
    d = msg.as_dict()
    assert d["Name"] == "Ada" and d["Email"] == "ada@acme.com" and d["Company"] == "Acme"
    assert d["Reason"] == "exploring AI" and d["Industry"] == "fintech"
    assert d["Reference"] == "REF-1"
    # Empty contact fields are dropped from the rendered text.
    text = msg.to_text()
    assert "Email: ada@acme.com" in text and "Reference: REF-1" in text


# --- Webhook adapter (httpx mocked) ---


class _Resp:
    def __init__(self, code: int) -> None:
        self.status_code = code


class _FakeAsyncClient:
    def __init__(self, *, code: int | None = None, exc: Exception | None = None) -> None:
        self._code = code
        self._exc = exc
        self.posted: dict | None = None

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *a: object) -> bool:
        return False

    async def post(self, url: str, **kwargs: object) -> _Resp:
        self.posted = {"url": url, **kwargs}
        if self._exc is not None:
            raise self._exc
        assert self._code is not None
        return _Resp(self._code)


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, **kw: object) -> _FakeAsyncClient:
    client = _FakeAsyncClient(**kw)  # type: ignore[arg-type]
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)
    return client


async def test_webhook_success_returns_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _patch_httpx(monkeypatch, code=200)
    result = await WebhookDeliveryClient("https://hook.example/x").deliver(_record())
    assert result.external_reference == "webhook-REF-1"
    # The reference is sent as an idempotency key + in the body (for receivers that dedupe).
    assert client.posted is not None
    assert client.posted["headers"]["Idempotency-Key"] == "REF-1"
    assert client.posted["json"]["reference"] == "REF-1"


async def _webhook_error(monkeypatch: pytest.MonkeyPatch, **kw: object) -> DeliveryError:
    _patch_httpx(monkeypatch, **kw)
    with pytest.raises(DeliveryError) as e:
        await WebhookDeliveryClient("https://hook").deliver(_record())
    return e.value


async def test_webhook_429_and_503_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    # Explicitly "not processed" → safe to retry (no duplicate).
    assert (await _webhook_error(monkeypatch, code=429)).retryable is True
    assert (await _webhook_error(monkeypatch, code=503)).retryable is True


async def test_webhook_other_5xx_parks(monkeypatch: pytest.MonkeyPatch) -> None:
    # 500 = server got the request, outcome ambiguous → park, never blind-retry.
    assert (await _webhook_error(monkeypatch, code=500)).retryable is False


async def test_webhook_4xx_and_3xx_are_permanent(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (await _webhook_error(monkeypatch, code=403)).retryable is False
    # 3xx: httpx doesn't follow redirects, so nothing was delivered — not a success.
    assert (await _webhook_error(monkeypatch, code=302)).retryable is False


async def test_webhook_connect_failure_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    # Connection never established → nothing sent → retryable.
    assert (await _webhook_error(monkeypatch, exc=httpx.ConnectError("refused"))).retryable is True
    assert (await _webhook_error(monkeypatch, exc=httpx.ConnectTimeout("t"))).retryable is True


async def test_webhook_post_connect_error_parks(monkeypatch: pytest.MonkeyPatch) -> None:
    # A read timeout can occur AFTER the bytes were sent → ambiguous → park.
    assert (await _webhook_error(monkeypatch, exc=httpx.ReadTimeout("read"))).retryable is False


async def test_webhook_invalid_url_parks_without_leaking(monkeypatch: pytest.MonkeyPatch) -> None:
    # InvalidURL is not an httpx.HTTPError — must still be caught (invariant #4) and parked.
    err = await _webhook_error(monkeypatch, exc=httpx.InvalidURL("bad"))
    assert err.retryable is False and isinstance(err, DeliveryError)


# --- Email adapter (smtplib mocked) ---


class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host: str, port: int, timeout: int | None = None) -> None:
        connect_exc = _EMAIL_STATE.get("connect_exc")
        if connect_exc is not None:
            raise connect_exc  # the SMTP() constructor connects
        self.sent: list[object] = []
        self.login_exc: Exception | None = _EMAIL_STATE.get("login_exc")
        self.send_exc: Exception | None = _EMAIL_STATE.get("send_exc")
        _FakeSMTP.instances.append(self)

    def quit(self) -> None:
        pass

    def __enter__(self) -> "_FakeSMTP":
        return self

    def __exit__(self, *a: object) -> bool:
        return False

    def starttls(self, *, context: object | None = None) -> None:
        # Mirror smtplib.SMTP.starttls, which accepts a verifying ssl context (the
        # adapter now passes ssl.create_default_context() — SECURITY_REVIEW_V1 M5).
        self.tls_context = context

    def login(self, user: str, password: str) -> None:
        if self.login_exc:
            raise self.login_exc

    def send_message(self, msg: object) -> None:
        if self.send_exc:
            raise self.send_exc
        self.sent.append(msg)


_EMAIL_STATE: dict[str, Exception | None] = {}


def _email_client() -> EmailDeliveryClient:
    return EmailDeliveryClient(
        host="smtp.x",
        port=587,
        user="u",
        password="p",
        sender="bot@x.com",
        recipient="team@x.com",
        use_tls=True,
    )


async def test_email_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _EMAIL_STATE.clear()
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    result = await _email_client().deliver(_record())
    assert result.external_reference == "email-REF-1"
    assert _FakeSMTP.instances[-1].sent  # a message was sent


async def test_email_auth_failure_is_permanent(monkeypatch: pytest.MonkeyPatch) -> None:
    _EMAIL_STATE.clear()
    _EMAIL_STATE["login_exc"] = smtplib.SMTPAuthenticationError(535, b"bad")
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    with pytest.raises(DeliveryError) as e:
        await _email_client().deliver(_record())
    assert e.value.retryable is False and e.value.code == "email_auth_failed"


async def test_email_connect_failure_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    # Never connected → nothing sent → safe to retry.
    _EMAIL_STATE.clear()
    _EMAIL_STATE["connect_exc"] = OSError("connection refused")
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    with pytest.raises(DeliveryError) as e:
        await _email_client().deliver(_record())
    assert e.value.retryable is True and e.value.code == "email_unreachable"


async def test_email_send_failure_parks(monkeypatch: pytest.MonkeyPatch) -> None:
    # A failure DURING send is ambiguous (may have been accepted) → park, do NOT retry.
    _EMAIL_STATE.clear()
    _EMAIL_STATE["send_exc"] = smtplib.SMTPServerDisconnected("down")
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    with pytest.raises(DeliveryError) as e:
        await _email_client().deliver(_record())
    assert e.value.retryable is False and e.value.code == "email_ambiguous"


async def test_email_recipient_refused_is_permanent(monkeypatch: pytest.MonkeyPatch) -> None:
    _EMAIL_STATE.clear()
    _EMAIL_STATE["send_exc"] = smtplib.SMTPRecipientsRefused({"team@x.com": (550, b"no")})
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    with pytest.raises(DeliveryError) as e:
        await _email_client().deliver(_record())
    assert e.value.retryable is False and e.value.code == "email_rejected"


# --- Factory: ENV selection + fallback ---


def _settings(**over: object) -> Settings:
    return Settings(_env_file=None, env="dev", **over)  # type: ignore[arg-type]


def test_factory_defaults_to_simulated() -> None:
    assert build_delivery_client(_settings()).channel == "simulated"


def test_factory_webhook_when_url_set() -> None:
    c = build_delivery_client(
        _settings(delivery_transport="webhook", delivery_webhook_url=SecretStr("https://hook"))
    )
    assert c.channel == "webhook"


def test_factory_webhook_falls_back_when_url_missing() -> None:
    c = build_delivery_client(_settings(delivery_transport="webhook"))
    assert c.channel == "simulated"  # unconfigured → mock (with a logged warning)


def test_factory_email_when_configured() -> None:
    c = build_delivery_client(
        _settings(
            delivery_transport="email",
            delivery_email_smtp_host="smtp.x",
            delivery_email_from="bot@x.com",
            delivery_email_to="team@x.com",
        )
    )
    assert c.channel == "email"


def test_factory_email_falls_back_when_incomplete() -> None:
    c = build_delivery_client(
        _settings(delivery_transport="email", delivery_email_smtp_host="smtp.x")
    )
    assert c.channel == "simulated"  # missing from/to → mock
