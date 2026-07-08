import json

from app.core.errors import (
    AppError,
    ErrorCode,
    _app_error_handler,
    _unhandled_error_handler,
)


def _body(response: object) -> dict[str, object]:
    return json.loads(response.body)  # type: ignore[attr-defined]


def test_app_error_defaults_from_code() -> None:
    err = AppError(ErrorCode.CONVERSATION_BUSY)
    assert err.http_status == 409
    assert err.retryable is True
    assert err.message  # non-empty default


def test_message_too_long_maps_to_413() -> None:
    assert AppError(ErrorCode.MESSAGE_TOO_LONG).http_status == 413


async def test_app_error_handler_envelope() -> None:
    response = await _app_error_handler(None, AppError(ErrorCode.CONVERSATION_BUSY))  # type: ignore[arg-type]
    assert response.status_code == 409
    body = _body(response)
    assert body["error"]["code"] == "CONVERSATION_BUSY"
    assert body["error"]["retryable"] is True
    assert "message" in body["error"]


async def test_unhandled_handler_never_leaks() -> None:
    response = await _unhandled_error_handler(None, ValueError("secret internal detail"))  # type: ignore[arg-type]
    assert response.status_code == 500
    body = _body(response)
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "secret internal detail" not in json.dumps(body)
