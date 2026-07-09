"""client_ip() must read the real client from the RIGHTMOST trusted proxy hop, not the
client-controlled leftmost X-Forwarded-For value (SECURITY_REVIEW_V1 M2)."""

import pytest
from starlette.requests import Request

from app.core import net


def _request(*, xff: str | None, peer: str | None = "10.0.0.9") -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    scope = {
        "type": "http",
        "headers": headers,
        "client": (peer, 12345) if peer is not None else None,
    }
    return Request(scope)


def test_one_hop_uses_real_peer_not_spoofed_leftmost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net.get_settings(), "trusted_proxy_hops", 1)
    # Attacker prepends a fake IP; Caddy appends the real client on the right.
    req = _request(xff="1.2.3.4, 203.0.113.7")
    assert net.client_ip(req) == "203.0.113.7"


def test_two_hops_peels_cdn_and_caddy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net.get_settings(), "trusted_proxy_hops", 2)
    # "spoof, realclient, cdn": with a CDN + Caddy (2 hops) the real client is 2nd from right.
    req = _request(xff="9.9.9.9, 203.0.113.7, 198.51.100.2")
    assert net.client_ip(req) == "203.0.113.7"


def test_falls_back_to_peer_when_header_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net.get_settings(), "trusted_proxy_hops", 1)
    assert net.client_ip(_request(xff=None)) == "10.0.0.9"


def test_fallback_when_fewer_hops_than_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net.get_settings(), "trusted_proxy_hops", 2)
    # Only one XFF entry but 2 trusted hops expected → don't trust it; use the peer.
    assert net.client_ip(_request(xff="1.2.3.4")) == "10.0.0.9"
