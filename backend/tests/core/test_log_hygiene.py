"""Log-hygiene audit (CLAUDE.md invariant #5, contracts §10).

Two nets: a STATIC scan asserting no forbidden field name appears as a key in any
``extra=`` dict passed to a logger anywhere in the source, and a RUNTIME check
that the formatter rejects a forbidden key. Together they make a careless log
call fail in CI rather than leak PII in production.
"""

import ast
import logging
from pathlib import Path

import pytest

from app.core.logging import FORBIDDEN_CONTEXT_KEYS, JsonFormatter

_ROOT = Path(__file__).resolve().parents[2]
_SCAN_DIRS = [_ROOT / "app", _ROOT / "scripts"]

_LOG_METHODS = frozenset({"debug", "info", "warning", "warn", "error", "exception", "critical"})


def _is_logger_call(node: ast.Call) -> bool:
    """A call of the form ``logger.<level>(...)`` (module or attribute logger)."""
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in _LOG_METHODS:
        return False
    recv = func.value
    return (isinstance(recv, ast.Name) and recv.id == "logger") or (
        isinstance(recv, ast.Attribute) and recv.attr == "logger"
    )


def _nonstatic_log_messages(source: str) -> list[int]:
    """Line numbers of logger calls that can carry PII in the event message —
    either a non-literal message (f-string, +/.format() interpolation) or extra
    positional %-args after the message."""
    tree = ast.parse(source)
    bad: list[int] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _is_logger_call(node) and node.args):
            continue
        msg = node.args[0]
        static_msg = isinstance(msg, ast.Constant) and isinstance(msg.value, str)
        has_format_args = len(node.args) > 1  # logger.info("x %s", val) — %-args
        if not static_msg or has_format_args:
            bad.append(node.lineno)
    return bad


def _string_keys(node: ast.AST) -> list[str]:
    """Every string-literal dict key anywhere under ``node``."""
    keys: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Dict):
            for key in child.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    keys.append(key.value)
    return keys


def _forbidden_in_extra(source: str) -> list[str]:
    tree = ast.parse(source)
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "extra":
                for key in _string_keys(kw.value):
                    if key in FORBIDDEN_CONTEXT_KEYS:
                        violations.append(key)
    return violations


def test_no_forbidden_field_in_any_log_call() -> None:
    offenders: dict[str, list[str]] = {}
    for scan_dir in _SCAN_DIRS:
        for path in scan_dir.rglob("*.py"):
            bad = _forbidden_in_extra(path.read_text(encoding="utf-8"))
            if bad:
                offenders[str(path.relative_to(_ROOT))] = bad
    assert not offenders, f"forbidden field(s) in log extra=: {offenders}"


def test_all_log_event_messages_are_static_literals() -> None:
    offenders: dict[str, list[int]] = {}
    for scan_dir in _SCAN_DIRS:
        for path in scan_dir.rglob("*.py"):
            bad = _nonstatic_log_messages(path.read_text(encoding="utf-8"))
            if bad:
                offenders[str(path.relative_to(_ROOT))] = bad
    assert not offenders, f"non-static log event message(s) (PII risk): {offenders}"


def test_scan_catches_interpolated_log_message() -> None:
    # Guard against the scanner silently passing everything.
    snippet = 'logger.info(f"turn failed for {user.email}")\nlogger.error("bad %s", email)'
    assert _nonstatic_log_messages(snippet) == [1, 2]
    assert _nonstatic_log_messages('logger.info("chat.turn.completed")') == []


def test_formatter_rejects_positional_args() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "failed for %s", ("a@b.com",), None)
    with pytest.raises(ValueError, match="static string"):
        formatter.format(record)


def test_formatter_rejects_email_in_event() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "user ada@acme.com", None, None)
    with pytest.raises(ValueError, match="email"):
        formatter.format(record)


def test_formatter_rejects_forbidden_context_key() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "evt", None, None)
    record.context = {"email": "ada@acme.com"}  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="forbidden field"):
        formatter.format(record)
