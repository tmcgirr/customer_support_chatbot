"""Read-only admin API (contracts §4). Every route requires admin Basic auth.

PII is masked by default (contracts §10): request contact emails and any email
embedded in a conversation transcript are shown as ``a***@acme.com``.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.admin.auth import AdminDep, AdminRoleDep
from app.api.deps import (
    AuditRepoDep,
    CanonicalRepoDep,
    JobRepoDep,
    PrivacyRepoDep,
    RepoDep,
    RequestRepoDep,
)
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.masking import mask_email, mask_pii_in_text
from app.domain.monitoring.alerts import evaluate_alerts

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class ConversationStats(BaseModel):
    total: int
    by_status: dict[str, int]
    by_outcome: dict[str, int]


class RequestStats(BaseModel):
    total: int
    by_type: dict[str, int]
    by_status: dict[str, int]


class DashboardResponse(BaseModel):
    conversations: ConversationStats
    requests: RequestStats
    unresolved_questions: int


class ConversationSummary(BaseModel):
    conversation_id: str
    status: str
    outcome: str | None
    message_count: int
    started_at: datetime
    last_activity_at: datetime


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummary]


class AdminMessage(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: str
    role: str
    content: str
    status: str
    prompt_version: str | None = None
    model: str | None = None
    trace_id: str | None = None
    created_at: datetime


class ConversationDetail(BaseModel):
    conversation_id: str
    status: str
    outcome: str | None
    started_at: datetime
    messages: list[AdminMessage]


class AdminRequest(BaseModel):
    request_id: str
    type: str
    status: str
    reference: str
    contact_email: str
    contact_company: str | None
    conversation_id: str
    destination: str
    delivery_channel: str | None = None
    external_reference: str | None = None
    last_delivery_error: str | None = None
    created_at: datetime


class RequestListResponse(BaseModel):
    requests: list[AdminRequest]


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class RevealRequestResponse(BaseModel):
    request_id: str
    contact: dict[str, Any]  # unmasked name/email/company
    fields: dict[str, Any]


class RevealMessage(BaseModel):
    id: str
    role: str
    content: str  # unmasked
    created_at: datetime


class RevealConversationResponse(BaseModel):
    conversation_id: str
    messages: list[RevealMessage]


class ActionResponse(BaseModel):
    ok: bool
    detail: str


class AuditEntry(BaseModel):
    actor: str
    role: str
    action: str
    target_type: str
    target_id: str
    reason: str | None
    at: datetime


class AuditListResponse(BaseModel):
    entries: list[AuditEntry]


class CanonicalSummary(BaseModel):
    intent: str
    name: str
    status: str
    owner: str
    review_date: datetime


class CanonicalListResponse(BaseModel):
    answers: list[CanonicalSummary]


class PrivacySummary(BaseModel):
    request_id: str
    type: str
    requester_email: str  # masked
    conversation_id: str | None
    verification_status: str
    status: str
    result_counts: dict[str, int] | None
    created_at: datetime
    completed_at: datetime | None


class PrivacyListResponse(BaseModel):
    requests: list[PrivacySummary]


class UnresolvedQuestion(BaseModel):
    question: str
    at: datetime
    conversation_id: str


class UnresolvedListResponse(BaseModel):
    questions: list[UnresolvedQuestion]


class SystemResponse(BaseModel):
    env: str
    version: str
    build: str
    feature_flags: dict[str, bool]


class MeResponse(BaseModel):
    username: str
    role: str


class AlertEntry(BaseModel):
    name: str
    severity: str
    count: int
    threshold: int
    message: str


class MonitoringResponse(BaseModel):
    """Machine-scrapable operational signals (admin-gated, no PII) — the source for
    the V1 alerts: queue depth, dead-letter, delivery failures, stuck erasures."""

    jobs_by_status: dict[str, int]  # pending/running/done/failed/dead_letter
    queue_depth: int  # pending jobs waiting to run
    dead_letter: int  # jobs that exhausted retries (ALERT if > 0)
    requests_by_status: dict[str, int]
    delivery_failed: int  # parked deliveries needing admin redeliver (ALERT if > 0)
    privacy_by_status: dict[str, int]
    privacy_failed: int  # verified erasures that couldn't complete (ALERT if > 0)
    unresolved_questions: int
    # Currently-firing alerts (same evaluation the worker logs) — empty when healthy.
    alerts: list[AlertEntry]


@router.get("/me", response_model=MeResponse)
async def me(admin: AdminDep) -> MeResponse:
    """The authenticated principal + role, so the UI can hide admin-only actions."""
    return MeResponse(username=admin.username, role=admin.role)


@router.get("/monitoring", response_model=MonitoringResponse)
async def monitoring(
    _admin: AdminDep,
    repo: RepoDep,
    request_repo: RequestRepoDep,
    jobs: JobRepoDep,
    privacy: PrivacyRepoDep,
) -> MonitoringResponse:
    """Operational counters for the alerting stack (scrape on an interval). All
    counts are IDs-only aggregates — never message content or PII (invariant #5)."""
    job_counts = await jobs.counts()
    request_counts = await request_repo.count_by("status")
    privacy_counts = await privacy.counts_by_status()
    alerts = evaluate_alerts(
        job_counts=job_counts,
        request_counts=request_counts,
        privacy_counts=privacy_counts,
        queue_depth_threshold=get_settings().alert_queue_depth_threshold,
    )
    return MonitoringResponse(
        jobs_by_status=job_counts,
        queue_depth=job_counts.get("pending", 0),
        dead_letter=job_counts.get("dead_letter", 0),
        requests_by_status=request_counts,
        delivery_failed=request_counts.get("delivery_failed", 0),
        privacy_by_status=privacy_counts,
        privacy_failed=privacy_counts.get("failed", 0),
        unresolved_questions=await repo.count_unsupported(),
        alerts=[
            AlertEntry(
                name=a.name,
                severity=a.severity,
                count=a.count,
                threshold=a.threshold,
                message=a.message,
            )
            for a in alerts
        ],
    )


@router.get("/system", response_model=SystemResponse)
async def system(_admin: AdminDep) -> SystemResponse:
    """Deploy/build metadata for operators (admin-gated so the public surface
    can't fingerprint env or build)."""
    settings = get_settings()
    return SystemResponse(
        env=settings.env,
        version=settings.app_version,
        build=settings.build_sha,
        feature_flags=settings.feature_flags,
    )


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(
    _admin: AdminDep, repo: RepoDep, request_repo: RequestRepoDep
) -> DashboardResponse:
    return DashboardResponse(
        conversations=ConversationStats(
            total=await repo.total(),
            by_status=await repo.count_by("status"),
            by_outcome=await repo.count_by("outcome"),
        ),
        requests=RequestStats(
            total=await request_repo.total(),
            by_type=await request_repo.count_by("type"),
            by_status=await request_repo.count_by("status"),
        ),
        unresolved_questions=await repo.count_unsupported(),
    )


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(_admin: AdminDep, repo: RepoDep) -> ConversationListResponse:
    conversations = await repo.list_recent()
    return ConversationListResponse(
        conversations=[
            ConversationSummary(
                conversation_id=c.id,
                status=c.status,
                outcome=c.outcome,
                message_count=c.message_count,
                started_at=c.started_at,
                last_activity_at=c.last_activity_at,
            )
            for c in conversations
        ]
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def conversation_detail(
    conversation_id: str, _admin: AdminDep, repo: RepoDep
) -> ConversationDetail:
    conversation = await repo.get_transcript(conversation_id)
    if conversation is None:
        raise AppError(ErrorCode.CONVERSATION_NOT_FOUND)
    return ConversationDetail(
        conversation_id=conversation.id,
        status=conversation.status,
        outcome=conversation.outcome,
        started_at=conversation.started_at,
        messages=[
            AdminMessage(
                id=m.id,
                role=m.role,
                content=mask_pii_in_text(m.content),
                status=m.status,
                prompt_version=m.prompt_version,
                model=m.model,
                trace_id=m.trace_id,
                created_at=m.created_at,
            )
            for m in conversation.messages
        ],
    )


@router.get("/requests", response_model=RequestListResponse)
async def list_requests(
    _admin: AdminDep,
    request_repo: RequestRepoDep,
    request_type: Annotated[str | None, Query(alias="type")] = None,
    request_status: Annotated[str | None, Query(alias="status")] = None,
) -> RequestListResponse:
    records = await request_repo.list_filtered(
        type_filter=request_type, status_filter=request_status
    )
    return RequestListResponse(
        requests=[
            AdminRequest(
                request_id=r.id,
                type=r.type,
                status=r.status,
                reference=r.reference,
                contact_email=mask_email(r.contact.email),
                contact_company=r.contact.company,
                conversation_id=r.conversation_id,
                destination=r.destination,
                delivery_channel=r.delivery_channel,
                external_reference=r.external_reference,
                last_delivery_error=r.last_delivery_error,
                created_at=r.created_at,
            )
            for r in records
        ]
    )


@router.get("/unresolved-questions", response_model=UnresolvedListResponse)
async def unresolved_questions(_admin: AdminDep, repo: RepoDep) -> UnresolvedListResponse:
    items = await repo.list_unsupported()
    return UnresolvedListResponse(
        questions=[
            UnresolvedQuestion(
                question=mask_pii_in_text(item["question"]),
                at=item["at"],
                conversation_id=item["conversation_id"],
            )
            for item in items
        ]
    )


# --- Privileged actions (admin role only; each writes an audit record) ---


@router.post("/requests/{request_id}/reveal", response_model=RevealRequestResponse)
async def reveal_request(
    request_id: str,
    body: ReasonBody,
    admin: AdminRoleDep,
    request_repo: RequestRepoDep,
    audit: AuditRepoDep,
) -> RevealRequestResponse:
    """Reveal a request's UNMASKED contact + fields (admin only, reason required,
    audited). Masking is the default everywhere else (contracts §10)."""
    record = await request_repo.get(request_id)
    if record is None:
        raise AppError(ErrorCode.INVALID_REQUEST, "Request not found.")
    await audit.record(
        actor=admin.username,
        role=admin.role,
        action="reveal_request",
        target_type="request",
        target_id=request_id,
        reason=body.reason,
    )
    return RevealRequestResponse(
        request_id=record.id,
        contact=record.contact.model_dump(),
        fields=dict(record.fields),
    )


@router.post("/conversations/{conversation_id}/reveal", response_model=RevealConversationResponse)
async def reveal_conversation(
    conversation_id: str,
    body: ReasonBody,
    admin: AdminRoleDep,
    repo: RepoDep,
    audit: AuditRepoDep,
) -> RevealConversationResponse:
    """Reveal a conversation's UNMASKED transcript (admin only, reason, audited)."""
    conversation = await repo.get_transcript(conversation_id)
    if conversation is None:
        raise AppError(ErrorCode.CONVERSATION_NOT_FOUND)
    await audit.record(
        actor=admin.username,
        role=admin.role,
        action="reveal_conversation",
        target_type="conversation",
        target_id=conversation_id,
        reason=body.reason,
    )
    return RevealConversationResponse(
        conversation_id=conversation.id,
        messages=[
            RevealMessage(id=m.id, role=m.role, content=m.content, created_at=m.created_at)
            for m in conversation.messages
        ],
    )


@router.post("/requests/{request_id}/redeliver", response_model=ActionResponse)
async def redeliver_request(
    request_id: str,
    body: ReasonBody,
    admin: AdminRoleDep,
    request_repo: RequestRepoDep,
    jobs: JobRepoDep,
    audit: AuditRepoDep,
) -> ActionResponse:
    """Retry a parked (delivery_failed) request: reset it to received and enqueue a
    fresh delivery job (admin only, audited). The delivery service still probes the
    destination first, so a redeliver of an actually-delivered request won't dup."""
    # Validate BEFORE auditing/side-effecting: a non-failed (or missing) request is a
    # 400 with no audit noise. Then audit BEFORE the delivery enqueue so an audit-write
    # failure can never leave an un-audited redelivery.
    record = await request_repo.get(request_id)
    if record is None or record.status != "delivery_failed":
        raise AppError(ErrorCode.INVALID_REQUEST, "No delivery-failed request to redeliver.")
    await audit.record(
        actor=admin.username,
        role=admin.role,
        action="redeliver_request",
        target_type="request",
        target_id=request_id,
        reason=body.reason,
    )
    # Guarded reset serializes concurrent redelivers: only the writer that flips
    # delivery_failed→received enqueues, so a double-click can't double-enqueue.
    reset = await request_repo.reset_for_redelivery(request_id)
    if reset:
        await jobs.enqueue("deliver_request", resource_id=request_id)
    return ActionResponse(ok=True, detail="Re-enqueued for delivery.")


@router.get("/canonical", response_model=CanonicalListResponse)
async def list_canonical(_admin: AdminDep, canonical: CanonicalRepoDep) -> CanonicalListResponse:
    answers = await canonical.list_answers()
    return CanonicalListResponse(
        answers=[
            CanonicalSummary(
                intent=a.intent,
                name=a.name,
                status=a.status,
                owner=a.owner,
                review_date=a.review_date,
            )
            for a in answers
        ]
    )


@router.post("/canonical/{intent}/approve", response_model=ActionResponse)
async def approve_canonical(
    intent: str,
    body: ReasonBody,
    admin: AdminRoleDep,
    canonical: CanonicalRepoDep,
    audit: AuditRepoDep,
) -> ActionResponse:
    """Approve a draft canonical answer so it starts being served (admin only, audited)."""
    # Validate a draft exists BEFORE auditing/mutating (no audit on a missing/already-
    # approved intent), then audit BEFORE the promote so the approval is always audited.
    existing = await canonical.get(intent)
    if existing is None or existing.status != "draft":
        raise AppError(ErrorCode.INVALID_REQUEST, "No draft canonical answer for that intent.")
    await audit.record(
        actor=admin.username,
        role=admin.role,
        action="approve_canonical",
        target_type="canonical_answer",
        target_id=intent,
        reason=body.reason,
    )
    await canonical.approve(intent)
    return ActionResponse(ok=True, detail=f"Approved canonical answer for {intent!r}.")


@router.get("/privacy-requests", response_model=PrivacyListResponse)
async def list_privacy_requests(_admin: AdminDep, privacy: PrivacyRepoDep) -> PrivacyListResponse:
    """Access/deletion requests awaiting or past verification (email masked)."""
    records = await privacy.list_recent()
    return PrivacyListResponse(
        requests=[
            PrivacySummary(
                request_id=r.id,
                type=r.type,
                requester_email=mask_email(r.requester_email),
                conversation_id=r.conversation_id,
                verification_status=r.verification_status,
                status=r.status,
                result_counts=r.result_counts,
                created_at=r.created_at,
                completed_at=r.completed_at,
            )
            for r in records
        ]
    )


@router.post("/privacy-requests/{request_id}/verify", response_model=ActionResponse)
async def verify_privacy_request(
    request_id: str,
    body: ReasonBody,
    admin: AdminRoleDep,
    privacy: PrivacyRepoDep,
    jobs: JobRepoDep,
    audit: AuditRepoDep,
) -> ActionResponse:
    """Confirm a subject's identity (admin only, reason required, audited). For a
    DELETION request this enqueues the ``privacy_delete`` worker job — the erasure
    itself never runs inline (invariant #13). Validate → audit → verify → enqueue so
    an invalid request neither audits nor acts and a verify is always recorded."""
    record = await privacy.get(request_id)
    if record is None or record.verification_status != "pending":
        raise AppError(ErrorCode.INVALID_REQUEST, "No pending privacy request to verify.")
    await audit.record(
        actor=admin.username,
        role=admin.role,
        action="verify_privacy_request",
        target_type="privacy_request",
        target_id=request_id,
        reason=body.reason,
    )
    verified = await privacy.mark_verified(request_id, verified_by=admin.username)
    # Guarded update: exactly one verifier wins, so at most one deletion job is enqueued.
    if verified is not None and verified.type == "deletion":
        await jobs.enqueue("privacy_delete", resource_id=request_id)
    detail = "Verified; erasure enqueued." if record.type == "deletion" else "Verified."
    return ActionResponse(ok=True, detail=detail)


@router.get("/audit", response_model=AuditListResponse)
async def list_audit(_admin: AdminDep, audit: AuditRepoDep) -> AuditListResponse:
    """The append-only admin audit trail (reveals, redelivers, approvals)."""
    records = await audit.list_recent()
    return AuditListResponse(
        entries=[
            AuditEntry(
                actor=r.actor,
                role=r.role,
                action=r.action,
                target_type=r.target_type,
                target_id=r.target_id,
                reason=r.reason,
                at=r.at,
            )
            for r in records
        ]
    )
