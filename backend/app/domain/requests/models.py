"""Unified request document (contracts §7, ADR-019).

Strategy-call, portal-support, and human-escalation share one collection and one
lifecycle. Local persistence (status ``received`` + a reference) is the user-facing
success; external delivery is a V1 background-job concern (not modeled here).
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RequestType = Literal["strategy_call", "portal_support", "human_escalation"]
RequestStatus = Literal["received", "delivering", "delivered", "delivery_failed"]
Destination = Literal["hubspot", "zendesk", "email", "none"]


class Contact(BaseModel):
    name: str | None = None
    email: str | None = None
    company: str | None = None


class RequestRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")
    type: RequestType
    conversation_id: str
    idempotency_key: str
    reference: str
    contact: Contact = Field(default_factory=Contact)
    fields: dict[str, Any] = Field(default_factory=dict)
    consent_version: str
    status: RequestStatus = "received"
    destination: Destination = "none"
    external_reference: str | None = None
    delivery_attempts: int = 0
    last_delivery_error: str | None = None
    # Which transport delivered it (simulated/webhook/email) — surfaced in admin so an
    # operator can see whether a request went out for real or via the mock (V1.5).
    delivery_channel: str | None = None
    # Set to "deleted" when a verified subject-erasure redacts this request's PII
    # (the skeleton is kept for delivery audit; V6).
    deletion_status: str | None = None
    created_at: datetime
    delivered_at: datetime | None = None
