"""Request service: replay-or-validate (contracts §3.4, §9), persist, set outcome."""

from datetime import UTC, datetime
from typing import Any

from app.core import ids
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.validation import is_valid_email
from app.domain.conversations.repository import ConversationRepository
from app.domain.jobs.repository import JobRepository
from app.domain.requests.models import Contact, RequestRecord, RequestType
from app.domain.requests.repository import RequestRepository

logger = get_logger("app.requests")

_ISSUE_CATEGORIES = {"forgot_password", "no_access", "error", "other"}
_MAX_FIELD_LEN = 4000

# Only these keys are persisted per type; anything else the client sends is dropped.
_ALLOWED_FIELDS: dict[RequestType, set[str]] = {
    "strategy_call": {"reason", "industry", "region"},
    "portal_support": {"issue_category", "description", "error_message", "steps_attempted"},
    "human_escalation": {"category", "original_question", "context_summary"},
}

# Request type -> conversation outcome (contracts §7).
_OUTCOME: dict[RequestType, str] = {
    "strategy_call": "strategy_call_requested",
    "portal_support": "support_request_created",
    "human_escalation": "human_escalation_created",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _valid_email(value: str | None) -> bool:
    return is_valid_email(value)


class RequestService:
    def __init__(
        self,
        request_repo: RequestRepository,
        conversation_repo: ConversationRepository,
        *,
        jobs: JobRepository | None = None,
        enable_delivery: bool = False,
    ) -> None:
        self._requests = request_repo
        self._conversations = conversation_repo
        self._jobs = jobs
        self._enable_delivery = enable_delivery

    def _validate(
        self,
        request_type: RequestType,
        contact: Contact,
        fields: dict[str, Any],
        confirmed: bool,
        consent_version: str,
    ) -> None:
        if not confirmed:
            raise AppError(ErrorCode.INVALID_REQUEST, "Confirmation is required.")
        if not consent_version:
            raise AppError(ErrorCode.INVALID_REQUEST, "A consent version is required.")

        if request_type == "strategy_call":
            if not _valid_email(contact.email):
                raise AppError(ErrorCode.INVALID_EMAIL)
            if not str(fields.get("reason", "")).strip():
                raise AppError(ErrorCode.INVALID_REQUEST, "A reason is required.")
        elif request_type == "portal_support":
            if not _valid_email(contact.email):
                raise AppError(ErrorCode.INVALID_EMAIL)
            if fields.get("issue_category") not in _ISSUE_CATEGORIES:
                raise AppError(ErrorCode.INVALID_REQUEST, "A valid issue category is required.")
            if not str(fields.get("description", "")).strip():
                raise AppError(ErrorCode.INVALID_REQUEST, "A description is required.")
        elif request_type == "human_escalation":
            # Contact is optional here; validate the email only if one was provided.
            if contact.email and not _valid_email(contact.email):
                raise AppError(ErrorCode.INVALID_EMAIL)
            if not str(fields.get("original_question", "")).strip():
                raise AppError(ErrorCode.INVALID_REQUEST, "The original question is required.")

    def _normalize_fields(
        self, request_type: RequestType, fields: dict[str, Any]
    ) -> dict[str, str]:
        """Whitelist known keys and bound each value's length (anti-bloat/injection)."""
        allowed = _ALLOWED_FIELDS[request_type]
        clean: dict[str, str] = {}
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            text = str(value)
            if len(text) > _MAX_FIELD_LEN:
                raise AppError(ErrorCode.MESSAGE_TOO_LONG, "A field value is too long.")
            clean[key] = text
        return clean

    async def submit(
        self,
        *,
        request_type: RequestType,
        conversation_id: str,
        contact: Contact,
        fields: dict[str, Any],
        consent_version: str,
        confirmed: bool,
        idempotency_key: str,
    ) -> tuple[RequestRecord, bool]:
        # Replay first: a duplicate key returns the original result WITHOUT
        # re-validating the (possibly different) payload (contracts §9).
        existing = await self._requests.find_by_key(conversation_id, idempotency_key)
        if existing is not None:
            await self._conversations.set_outcome(conversation_id, _OUTCOME[existing.type])
            return existing, True

        self._validate(request_type, contact, fields, confirmed, consent_version)
        record = RequestRecord(
            id=ids.request_id(),
            type=request_type,
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
            reference=ids.request_reference(),
            contact=contact,
            fields=self._normalize_fields(request_type, fields),
            consent_version=consent_version,
            created_at=_now(),
        )
        stored, duplicate = await self._requests.create_or_replay(record)
        # Idempotent $set; run on both fresh and race-replay so a request whose
        # outcome write previously failed is reconciled on retry.
        await self._conversations.set_outcome(conversation_id, _OUTCOME[stored.type])
        # Enqueue delivery exactly once — only the fresh-create winner, and only when
        # delivery is enabled (dark-launch flag). The browser never triggers delivery
        # directly; the worker owns the external side effect (invariant #11).
        if not duplicate and self._enable_delivery and self._jobs is not None:
            await self._jobs.enqueue("deliver_request", resource_id=stored.id)
        return stored, duplicate
