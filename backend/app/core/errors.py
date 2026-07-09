"""Error contract (contracts §6).

A fixed set of error codes; clients never see raw exceptions or provider
messages. Domain code raises ``AppError``; the registered handlers translate it
(and validation / unexpected errors) into the JSON error envelope:

    { "error": { "code", "message", "retryable", "request_id" } }
"""

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import get_logger, request_id_var

logger = get_logger("app.error")


class ErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_EMAIL = "INVALID_EMAIL"
    UNAUTHORIZED_SESSION = "UNAUTHORIZED_SESSION"
    CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
    MESSAGE_TOO_LONG = "MESSAGE_TOO_LONG"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    CONVERSATION_BUSY = "CONVERSATION_BUSY"
    DUPLICATE_ACTION = "DUPLICATE_ACTION"
    RATE_LIMIT = "RATE_LIMIT"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    RETRIEVAL_UNAVAILABLE = "RETRIEVAL_UNAVAILABLE"
    PERSISTENCE_UNAVAILABLE = "PERSISTENCE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.INVALID_EMAIL: 400,
    ErrorCode.UNAUTHORIZED_SESSION: 401,
    ErrorCode.CONVERSATION_NOT_FOUND: 404,
    ErrorCode.MESSAGE_TOO_LONG: 413,
    ErrorCode.PAYLOAD_TOO_LARGE: 413,
    ErrorCode.CONVERSATION_BUSY: 409,
    # DUPLICATE_ACTION is a *replay detail*, not a failure: duplicate writes must
    # return the original result with HTTP 200 at the route (contracts §9). This
    # 409 is only a fallback should it ever be raised directly. See DECISIONS_LOG.
    ErrorCode.DUPLICATE_ACTION: 409,
    ErrorCode.RATE_LIMIT: 429,
    ErrorCode.MODEL_UNAVAILABLE: 503,
    ErrorCode.RETRIEVAL_UNAVAILABLE: 503,
    ErrorCode.PERSISTENCE_UNAVAILABLE: 503,
    ErrorCode.INTERNAL_ERROR: 500,
}

# RATE_LIMIT is intentionally absent: the per-conversation cap is terminal, so it
# defaults to non-retryable. The per-IP creation cap (Phase 8) passes retryable=True.
_RETRYABLE: dict[ErrorCode, bool] = {
    ErrorCode.CONVERSATION_BUSY: True,
    ErrorCode.MODEL_UNAVAILABLE: True,
    ErrorCode.RETRIEVAL_UNAVAILABLE: True,
    ErrorCode.PERSISTENCE_UNAVAILABLE: True,
}

_DEFAULT_MESSAGE: dict[ErrorCode, str] = {
    ErrorCode.INVALID_REQUEST: "The request was invalid.",
    ErrorCode.INVALID_EMAIL: "Please provide a valid email address.",
    ErrorCode.UNAUTHORIZED_SESSION: "Your session is invalid or has expired.",
    ErrorCode.CONVERSATION_NOT_FOUND: "Conversation not found.",
    ErrorCode.MESSAGE_TOO_LONG: "Your message is too long.",
    ErrorCode.PAYLOAD_TOO_LARGE: "The request body is too large.",
    ErrorCode.CONVERSATION_BUSY: "Please wait for the current response to complete.",
    ErrorCode.DUPLICATE_ACTION: "This action was already submitted.",
    ErrorCode.RATE_LIMIT: "You've reached a usage limit. Please try another contact option.",
    ErrorCode.MODEL_UNAVAILABLE: "The assistant is temporarily unavailable.",
    ErrorCode.RETRIEVAL_UNAVAILABLE: "Knowledge search is temporarily unavailable.",
    ErrorCode.PERSISTENCE_UNAVAILABLE: "The service is temporarily unavailable.",
    ErrorCode.INTERNAL_ERROR: "An unexpected error occurred.",
}


class AppError(Exception):
    """Raised by domain code; carries everything the error envelope needs."""

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        *,
        retryable: bool | None = None,
        http_status: int | None = None,
        detail: str | None = None,
    ) -> None:
        self.code = code
        self.message = message or _DEFAULT_MESSAGE[code]
        self.retryable = _RETRYABLE.get(code, False) if retryable is None else retryable
        self.http_status = http_status or _HTTP_STATUS[code]
        self.detail = detail
        super().__init__(self.message)


def _envelope(code: ErrorCode, message: str, retryable: bool, detail: str | None) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code.value,
        "message": message,
        "retryable": retryable,
        "request_id": request_id_var.get(),
    }
    if detail is not None:
        error["detail"] = detail
    return {"error": error}


def error_response(code: ErrorCode, message: str | None = None) -> JSONResponse:
    """Build the JSON error envelope + status for a code, for callers OUTSIDE the
    exception-handler stack (e.g. HTTP middleware, which raises can't reach a handler)."""
    return JSONResponse(
        status_code=_HTTP_STATUS[code],
        content=_envelope(
            code, message or _DEFAULT_MESSAGE[code], _RETRYABLE.get(code, False), None
        ),
    )


async def _app_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    logger.info(
        "app.error",
        extra={"context": {"error_code": exc.code.value, "status": exc.http_status}},
    )
    return JSONResponse(
        status_code=exc.http_status,
        content=_envelope(exc.code, exc.message, exc.retryable, exc.detail),
    )


async def _validation_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    code = ErrorCode.INVALID_REQUEST
    logger.info("app.error", extra={"context": {"error_code": code.value, "status": 400}})
    return JSONResponse(
        status_code=400,
        content=_envelope(code, _DEFAULT_MESSAGE[code], False, None),
    )


async def _unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    code = ErrorCode.INTERNAL_ERROR
    # exc_info logs the exception *type* only (JsonFormatter drops the message).
    logger.error("app.unhandled", exc_info=exc, extra={"context": {"error_code": code.value}})
    return JSONResponse(
        status_code=500,
        content=_envelope(code, _DEFAULT_MESSAGE[code], False, None),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
