"""Structured JSON logging.

Invariant (CLAUDE.md #5, contracts §10): logs reference IDs only. No message
content, no emails, no request/response bodies, no tokens, no tool payloads.

Log records carry a fixed set of top-level keys plus an optional ``context``
dict of scalar identifiers (``conversation_id``, ``request_id``, ``error_code``,
``status``, ``duration_ms``, ...). Callers pass structured fields via
``logger.info("event.name", extra={"context": {...}})``. Field names that could
carry user content are rejected at emit time so a careless call fails loudly in
tests rather than leaking silently in production.
"""

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

from app.core.ids import log_request_id

# request_id for the in-flight HTTP request, bound by RequestContextMiddleware.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Keys that must never appear in a log record — they can carry user content/PII.
FORBIDDEN_CONTEXT_KEYS: frozenset[str] = frozenset(
    {"content", "message", "text", "email", "phone", "body", "token", "prompt", "query"}
)

# Top-level record keys that context must not override.
_RESERVED_CONTEXT_KEYS: frozenset[str] = frozenset({"ts", "level", "logger", "event"})


def _reject_unsafe_context(value: object) -> None:
    """Recursively reject forbidden keys anywhere in the context tree."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_CONTEXT_KEYS:
                raise ValueError(f"forbidden field in log context: {key!r}")
            _reject_unsafe_context(item)
    elif isinstance(value, list | tuple):
        for item in value:
            _reject_unsafe_context(item)


def new_request_id() -> str:
    return log_request_id()


class JsonFormatter(logging.Formatter):
    """Render a log record as a single-line JSON object with whitelisted keys."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }

        rid = request_id_var.get()
        if rid is not None:
            payload["request_id"] = rid

        context = getattr(record, "context", None)
        if context is not None:
            if not isinstance(context, dict):
                raise TypeError("log 'context' must be a dict of scalar identifiers")
            reserved = _RESERVED_CONTEXT_KEYS.intersection(context)
            if reserved:
                raise ValueError(f"log context may not override reserved keys: {sorted(reserved)}")
            _reject_unsafe_context(context)
            payload.update(context)

        if record.exc_info:
            # Exception *type* only — never the message, which may echo user input.
            exc_type = record.exc_info[0]
            payload["error"] = exc_type.__name__ if exc_type else "Exception"

        return json.dumps(payload, separators=(",", ":"))


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn's access log echoes query strings/paths that can carry PII; silence it.
    logging.getLogger("uvicorn.access").disabled = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
