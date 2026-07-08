"""Stateless HMAC-signed session tokens (contracts §2).

    payload   = { cid, kid, iat, exp }
    token     = base64url(payload) + "." + base64url(HMAC_SHA256(secret, base64url(payload)))

No session collection exists. Secrets are versioned by key id (`kid`) so keys can
rotate: a token minted under a retired key still verifies as long as that key
remains in the ring (`Settings.session_key_ring`). Any validation failure raises
``UNAUTHORIZED_SESSION`` — the caller never learns why.
"""

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode

DEFAULT_TTL_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class SessionClaims:
    cid: str
    kid: str
    iat: int
    exp: int


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(payload_b64: str, secret: str) -> str:
    mac = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    return _b64url_encode(mac)


def _unauthorized() -> AppError:
    return AppError(ErrorCode.UNAUTHORIZED_SESSION)


def mint_session_token(
    cid: str, *, ttl_seconds: int = DEFAULT_TTL_SECONDS, now: int | None = None
) -> str:
    settings = get_settings()
    issued = int(time.time()) if now is None else now
    payload = {
        "cid": cid,
        "kid": settings.session_key_id,
        "iat": issued,
        "exp": issued + ttl_seconds,
    }
    payload_b64 = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    )
    secret = settings.session_key_ring[settings.session_key_id]
    return f"{payload_b64}.{_sign(payload_b64, secret)}"


def verify_session_token(token: str, *, now: int | None = None) -> SessionClaims:
    settings = get_settings()
    # Everything that touches attacker-controlled bytes stays in the try so any
    # malformed input maps to UNAUTHORIZED_SESSION, never a 500. In particular the
    # header-supplied signature may carry non-ASCII code points, so compare bytes.
    try:
        payload_b64, signature = token.split(".", 1)
        payload = json.loads(_b64url_decode(payload_b64))
        cid = str(payload["cid"])
        kid = str(payload["kid"])
        iat = int(payload["iat"])
        exp = int(payload["exp"])
        secret = settings.session_key_ring.get(kid)
        if secret is None:
            raise ValueError("unknown key id")
        expected = _sign(payload_b64, secret)
        if not hmac.compare_digest(expected.encode("ascii"), signature.encode("ascii")):
            raise ValueError("signature mismatch")
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise _unauthorized() from exc

    current = int(time.time()) if now is None else now
    if current >= exp:
        raise _unauthorized()

    return SessionClaims(cid=cid, kid=kid, iat=iat, exp=exp)
