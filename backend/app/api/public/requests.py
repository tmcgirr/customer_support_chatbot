"""Unified requests endpoint (contracts §3.4, §9) — the one write path.

The browser calls this after the user reviews and confirms a form. The model is
never in the write path (ADR-016). Duplicate Idempotency-Key replays the original
result with HTTP 200 and ``duplicate: true`` (contracts §9).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field

from app.api.deps import RateLimiterDep, RequestServiceDep, TokenDep
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.net import client_ip
from app.domain.requests.models import Contact, RequestType

router = APIRouter(prefix="/api/v1/requests", tags=["requests"])


class SubmitRequestBody(BaseModel):
    type: RequestType
    conversation_id: str
    contact: Contact = Field(default_factory=Contact)
    fields: dict[str, Any] = Field(default_factory=dict)
    consent_version: str
    confirmed: bool = False


class SubmitRequestResponse(BaseModel):
    request_id: str
    status: str
    reference: str
    duplicate: bool = False


@router.post("", response_model=SubmitRequestResponse)
async def submit_request(
    body: SubmitRequestBody,
    request: Request,
    claims: TokenDep,
    service: RequestServiceDep,
    rate_limiter: RateLimiterDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> SubmitRequestResponse:
    settings = get_settings()
    if claims.cid != body.conversation_id:
        raise AppError(ErrorCode.UNAUTHORIZED_SESSION)
    if not idempotency_key:
        raise AppError(ErrorCode.INVALID_REQUEST, "An Idempotency-Key header is required.")
    if len(idempotency_key) > 200:
        raise AppError(ErrorCode.INVALID_REQUEST, "The Idempotency-Key is too long.")

    # Cap submissions per-conversation AND per-IP: each fresh key is one external
    # delivery, so an unthrottled session could flood the team inbox (SECURITY_REVIEW_V1
    # H1). Caps are generous, so a legit idempotent retry (same key, dropped response)
    # stays within headroom and still replays.
    within_conversation = await rate_limiter.hit(
        f"req:{body.conversation_id}",
        limit=settings.request_conversation_cap,
        window_seconds=settings.request_conversation_window_seconds,
    )
    within_ip = await rate_limiter.hit(
        f"reqip:{client_ip(request)}",
        limit=settings.request_ip_cap,
        window_seconds=settings.request_ip_window_seconds,
    )
    if not (within_conversation and within_ip):
        raise AppError(ErrorCode.RATE_LIMIT, retryable=True)

    record, duplicate = await service.submit(
        request_type=body.type,
        conversation_id=body.conversation_id,
        contact=body.contact,
        fields=body.fields,
        consent_version=body.consent_version,
        confirmed=body.confirmed,
        idempotency_key=idempotency_key,
    )
    return SubmitRequestResponse(
        request_id=record.id,
        status=record.status,
        reference=record.reference,
        duplicate=duplicate,
    )
