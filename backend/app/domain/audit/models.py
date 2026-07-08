"""Admin audit record (contracts §4, §10).

An append-only trail of privileged admin actions — PII reveal/export, content
approval, delivery redeliver, deletion. Every reveal carries a ``reason``. Records
are never updated or deleted (write-once). No PII in the record itself: it holds
the actor, the action, the LOCAL target id, and the operator-supplied reason.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AuditAction = Literal[
    "reveal_request",
    "reveal_conversation",
    "redeliver_request",
    "approve_canonical",
    "export",
    "delete",
]


class AuditRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")
    actor: str  # admin username / IdP subject
    role: str
    action: AuditAction
    target_type: str  # e.g. "request", "conversation", "canonical_answer"
    target_id: str  # a LOCAL id (req_/cnv_/intent) — never a provider/PII value
    reason: str | None = None
    at: datetime
