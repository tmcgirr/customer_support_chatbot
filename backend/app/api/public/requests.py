"""Unified requests endpoint (contracts §3.4, §9) — the one write path.

The browser calls this after the user reviews and confirms a form. The model is
never in the write path (ADR-016). Duplicate Idempotency-Key replays the original
result with HTTP 200 and ``duplicate: true`` (contracts §9).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from app.api.deps import RequestServiceDep, TokenDep
from app.core.errors import AppError, ErrorCode
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
    claims: TokenDep,
    service: RequestServiceDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> SubmitRequestResponse:
    if claims.cid != body.conversation_id:
        raise AppError(ErrorCode.UNAUTHORIZED_SESSION)
    if not idempotency_key:
        raise AppError(ErrorCode.INVALID_REQUEST, "An Idempotency-Key header is required.")
    if len(idempotency_key) > 200:
        raise AppError(ErrorCode.INVALID_REQUEST, "The Idempotency-Key is too long.")

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
