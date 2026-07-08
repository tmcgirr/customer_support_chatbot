"""Privacy-request document model (contracts §7).

A data subject asks to access or delete their data via the public
``POST /api/v1/privacy/requests`` endpoint. The request is recorded here with
``verification_status = pending``; an admin verifies the requester's identity
(out of band) before any deletion executes (CLAUDE.md invariant #13 — no ad-hoc
deletes on the request path). Deletion itself is carried out asynchronously by
the ``privacy_delete`` worker job, never inline.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PrivacyRequestType = Literal["access", "deletion"]
# Identity verification (the requester is who they claim); gates execution.
VerificationStatus = Literal["pending", "verified", "rejected"]
# Fulfillment lifecycle of the request itself.
PrivacyRequestStatus = Literal["open", "completed", "failed"]


class PrivacyRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")
    type: PrivacyRequestType
    # Optional conversation the subject names as theirs. Deletion also matches all
    # requests (and their conversations) by ``requester_email``.
    conversation_id: str | None = None
    requester_email: str
    verification_status: VerificationStatus = "pending"
    status: PrivacyRequestStatus = "open"
    # Set when an admin verifies (identity confirmed out of band).
    verified_by: str | None = None
    verified_at: datetime | None = None
    completed_at: datetime | None = None
    # Deletion result counts per collection (no PII); shown in admin, used in audit.
    result_counts: dict[str, int] | None = None
    last_error: str | None = None
    created_at: datetime
