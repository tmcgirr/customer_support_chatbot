"""Request network helpers."""

from fastapi import Request


def client_ip(request: Request) -> str:
    """Best-effort client IP for abuse control.

    Prefers the leftmost ``X-Forwarded-For`` entry (the original client when
    behind a trusted proxy/LB, which is the POC deploy shape), falling back to
    the direct peer. NOTE: ``X-Forwarded-For`` is client-spoofable unless the
    edge proxy overwrites it — acceptable for a coarse per-IP creation cap, not
    for anything security-critical.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"
