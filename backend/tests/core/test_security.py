import pytest

from app.core.errors import AppError, ErrorCode
from app.core.security import mint_session_token, verify_session_token


def test_mint_then_verify_round_trip() -> None:
    token = mint_session_token("cnv_abc")
    claims = verify_session_token(token)
    assert claims.cid == "cnv_abc"
    assert claims.kid == "k1"
    assert claims.exp > claims.iat


def test_expired_token_is_rejected() -> None:
    token = mint_session_token("cnv_abc", ttl_seconds=100, now=1_000)
    with pytest.raises(AppError) as exc_info:
        verify_session_token(token, now=1_101)
    assert exc_info.value.code is ErrorCode.UNAUTHORIZED_SESSION


def test_tampered_payload_is_rejected() -> None:
    token = mint_session_token("cnv_abc")
    payload_b64, signature = token.split(".", 1)
    forged = mint_session_token("cnv_EVIL").split(".", 1)[0]
    with pytest.raises(AppError):
        verify_session_token(f"{forged}.{signature}")


def test_garbage_token_is_rejected() -> None:
    with pytest.raises(AppError):
        verify_session_token("not-a-token")


def test_unknown_key_id_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    token = mint_session_token("cnv_abc")
    # Rotate the ring so the token's kid is no longer present.
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(type(settings), "session_key_ring", property(lambda _self: {"k9": "other"}))
    with pytest.raises(AppError):
        verify_session_token(token)


def test_non_ascii_signature_is_unauthorized_not_internal_error() -> None:
    # A signature with non-ASCII bytes must NOT escape as a TypeError/500.
    payload_b64 = mint_session_token("cnv_abc").split(".", 1)[0]
    with pytest.raises(AppError) as exc_info:
        verify_session_token(f"{payload_b64}.\x80\x81bad")
    assert exc_info.value.code is ErrorCode.UNAUTHORIZED_SESSION
