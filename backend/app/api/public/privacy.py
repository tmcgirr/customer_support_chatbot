"""Public privacy-request endpoint (contracts §3.5).

A data subject asks to access or delete their data. This endpoint is
UNAUTHENTICATED (a subject may not hold a session) and deliberately reveals
NOTHING about whether we hold any data — it always returns the same generic
acknowledgement. Actual deletion never happens here: the request is recorded for
an admin to verify identity out of band, after which the worker executes it
(CLAUDE.md invariant #13). Rate-limited per IP to blunt enumeration/abuse.
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.deps import PrivacyRepoDep, RateLimiterDep
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.net import client_ip
from app.core.validation import is_valid_email
from app.domain.privacy.models import PrivacyRequestType

router = APIRouter(prefix="/api/v1/privacy", tags=["privacy"])

# Fixed acknowledgement — identical for every input, so the response can never be
# used to probe whether a given email/conversation exists in our data.
_ACK = (
    "Your request has been received. If we hold data associated with this email, "
    "we will verify your identity and follow up. Please allow up to 30 days."
)


class PrivacyRequestBody(BaseModel):
    type: PrivacyRequestType
    email: str
    conversation_id: str | None = None


class PrivacyRequestResponse(BaseModel):
    request_id: str
    status: str
    message: str


@router.post("/requests", response_model=PrivacyRequestResponse)
async def submit_privacy_request(
    body: PrivacyRequestBody,
    request: Request,
    privacy: PrivacyRepoDep,
    rate_limiter: RateLimiterDep,
) -> PrivacyRequestResponse:
    settings = get_settings()
    allowed = await rate_limiter.hit(
        f"privacy:{client_ip(request)}",
        limit=settings.privacy_request_ip_cap,
        window_seconds=settings.privacy_request_ip_window_seconds,
    )
    if not allowed:
        raise AppError(ErrorCode.RATE_LIMIT, retryable=True)
    if not is_valid_email(body.email):
        raise AppError(ErrorCode.INVALID_EMAIL)

    record = await privacy.create(
        request_type=body.type,
        requester_email=body.email.strip(),
        conversation_id=body.conversation_id,
    )
    # Always the same shape/message regardless of whether any data exists.
    return PrivacyRequestResponse(request_id=record.id, status="received", message=_ACK)
