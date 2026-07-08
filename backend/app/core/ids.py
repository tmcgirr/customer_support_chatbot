"""ULID-based identifiers with domain prefixes (contracts §1).

Public APIs expose only these local IDs — never provider or Mongo internals.
ULIDs are lexicographically sortable by creation time, which is convenient for
Mongo ``_id`` ordering and log correlation.
"""

from ulid import ULID


def prefixed_id(prefix: str) -> str:
    return f"{prefix}_{ULID()}"


def conversation_id() -> str:
    return prefixed_id("cnv")


def message_id() -> str:
    return prefixed_id("msg")


def run_id() -> str:
    return prefixed_id("run")


def request_id() -> str:
    return prefixed_id("req")


def knowledge_source_id() -> str:
    return prefixed_id("kbs")


def canonical_answer_id() -> str:
    return prefixed_id("can")


def feedback_id() -> str:
    return prefixed_id("fbk")


def privacy_request_id() -> str:
    return prefixed_id("pvr")


def job_id() -> str:
    return prefixed_id("job")


def eval_case_id() -> str:
    return prefixed_id("evc")


def log_request_id() -> str:
    """Correlation id stamped on each HTTP request (contracts §6 uses `rid_`)."""
    return prefixed_id("rid")
