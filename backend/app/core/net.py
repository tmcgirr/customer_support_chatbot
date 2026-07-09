"""Request network helpers."""

from fastapi import Request

from app.core.config import get_settings


def client_ip(request: Request) -> str:
    """Best-effort client IP for abuse control, resistant to ``X-Forwarded-For`` spoofing.

    A client can put ANY value in ``X-Forwarded-For``; a trusted reverse proxy (our
    Caddy) APPENDS the real peer it saw. So the real client is the Nth entry FROM THE
    RIGHT, where ``N = trusted_proxy_hops`` (1 for Caddy alone; 2 once a CDN/WAF fronts
    it). Reading the rightmost trusted hop — never the leftmost, client-controlled value
    — is what makes the per-IP caps meaningful (docs/SECURITY_REVIEW_V1.md M2). If the
    header is missing or has fewer hops than configured, fall back to the direct peer.
    """
    hops = get_settings().trusted_proxy_hops
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and hops > 0:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return request.client.host if request.client else "unknown"
