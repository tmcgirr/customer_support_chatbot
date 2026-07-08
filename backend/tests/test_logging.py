import json
import logging
from typing import Any

import pytest

from app.core.logging import JsonFormatter, request_id_var


def _record(msg: str, context: dict[str, Any] | None = None) -> logging.LogRecord:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, msg, None, None)
    if context is not None:
        record.context = context  # type: ignore[attr-defined]
    return record


def test_formatter_emits_whitelisted_keys_only() -> None:
    token = request_id_var.set("rid_abc")
    try:
        out = json.loads(
            JsonFormatter().format(
                _record("chat.turn", {"conversation_id": "cnv_1", "status": 200})
            )
        )
    finally:
        request_id_var.reset(token)

    assert out["event"] == "chat.turn"
    assert out["request_id"] == "rid_abc"
    assert out["conversation_id"] == "cnv_1"
    assert set(out) <= {
        "ts",
        "level",
        "logger",
        "event",
        "request_id",
        "conversation_id",
        "status",
    }


@pytest.mark.parametrize("field", ["content", "message", "email", "body", "token", "prompt"])
def test_formatter_rejects_message_content_fields(field: str) -> None:
    with pytest.raises(ValueError, match="forbidden field"):
        JsonFormatter().format(_record("chat.turn", {field: "secret user text"}))
