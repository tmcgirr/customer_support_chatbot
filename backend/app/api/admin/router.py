"""Read-only admin API (contracts §4). Every route requires admin Basic auth.

PII is masked by default (contracts §10): request contact emails and any email
embedded in a conversation transcript are shown as ``a***@acme.com``.
"""

import hashlib
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from app.api.admin.auth import AdminDep, AdminRoleDep
from app.api.deps import (
    AuditRepoDep,
    CanonicalRepoDep,
    InsightsRepoDep,
    JobRepoDep,
    KnowledgeRepoDep,
    KnowledgeStoreDep,
    PrivacyRepoDep,
    RepoDep,
    RequestRepoDep,
)
from app.core import ids
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.masking import mask_email, mask_pii_in_text
from app.domain.insights.gaps import rank_gaps
from app.domain.insights.models import InsightsReport
from app.domain.knowledge.models import KnowledgeSource
from app.domain.knowledge.store import KnowledgeStore, KnowledgeStoreError
from app.domain.monitoring.alerts import evaluate_alerts

logger = get_logger("app.admin")

# Cap uploaded knowledge files (markdown/text docs — a few hundred KB is plenty).
_MAX_KNOWLEDGE_BYTES = 5 * 1024 * 1024

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class ConversationStats(BaseModel):
    total: int
    by_status: dict[str, int]
    by_outcome: dict[str, int]
    # V1.5 analytics: computed topic/intent labels ("unset" = not yet labeled).
    by_topic: dict[str, int]
    by_intent: dict[str, int]


class RequestStats(BaseModel):
    total: int
    by_type: dict[str, int]
    by_status: dict[str, int]


class DashboardResponse(BaseModel):
    conversations: ConversationStats
    requests: RequestStats
    unresolved_questions: int


class FunnelStage(BaseModel):
    """Conversion funnel: visited → asked → engaged → requested (contact)."""

    visited: int
    asked: int
    engaged: int
    requested: int


class FunnelResponse(BaseModel):
    overall: FunnelStage
    by_topic: dict[str, FunnelStage]
    by_intent: dict[str, FunnelStage]


class ConversationSummary(BaseModel):
    conversation_id: str
    status: str
    outcome: str | None
    message_count: int
    summary: str | None = None  # computed TL;DR (null until the summarizer runs)
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
    summary: str | None = None  # computed TL;DR
    key_points: list[str] = []  # computed key points
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


class InsightsCluster(BaseModel):
    label: str
    representative_question: str
    sample_questions: list[str]
    size: int
    dominant_topic: str | None
    coverage: str
    conversation_ids: list[str]
    proposed_question: str | None
    proposed_answer: str | None
    # The canonical DRAFT intent to approve (if the engine auto-drafted one); the admin
    # approves it through the existing canonical gate. Never a provider id (invariant #6).
    proposed_canonical_intent: str | None


class InsightsReportResponse(BaseModel):
    period_type: str
    period_key: str
    generated_at: datetime
    window_start: datetime
    window_end: datetime
    conversations_analyzed: int
    conversations_in_period: int  # > analyzed ⇒ only a capped sample was clustered
    clusters: list[InsightsCluster]
    summary: str


class InsightsLatestResponse(BaseModel):
    report: InsightsReportResponse | None


class InsightsReportItem(BaseModel):
    report_id: str
    period_type: str
    period_key: str
    generated_at: datetime
    conversations_analyzed: int
    cluster_count: int


class InsightsListResponse(BaseModel):
    reports: list[InsightsReportItem]


class KnowledgeGapItem(BaseModel):
    key: str
    label: str
    representative_question: str  # masked (contracts §10) — question text is PII by default
    coverage: str
    total_asked: int  # magnitude: questions asked across the window
    days_seen: int  # persistence: distinct daily reports it appeared in
    proposed_question: str | None
    proposed_answer: str | None
    proposed_canonical_intent: str | None  # approve via the existing gate; never a provider id
    last_period_key: str
    last_generated_at: datetime


class KnowledgeGapsResponse(BaseModel):
    window_days: int
    daily_reports: int  # daily reports aggregated (0 ⇒ none yet, so no gaps to rank)
    gaps: list[KnowledgeGapItem]


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
            by_topic=await repo.count_by("labels.topic"),
            by_intent=await repo.count_by("labels.intent"),
        ),
        requests=RequestStats(
            total=await request_repo.total(),
            by_type=await request_repo.count_by("type"),
            by_status=await request_repo.count_by("status"),
        ),
        unresolved_questions=await repo.count_unsupported(),
    )


_EMPTY_FUNNEL = {"visited": 0, "asked": 0, "engaged": 0, "requested": 0}


@router.get("/funnel", response_model=FunnelResponse)
async def funnel(_admin: AdminDep, repo: RepoDep) -> FunnelResponse:
    """Conversion funnel (visited → asked → engaged → requested), overall and broken down
    by conversation topic + intent. Computed live from conversation counts (no PII)."""
    overall = (await repo.funnel(None)).get("all", _EMPTY_FUNNEL)
    by_topic = await repo.funnel("labels.topic")
    by_intent = await repo.funnel("labels.intent")
    return FunnelResponse(
        overall=FunnelStage(**overall),
        by_topic={k: FunnelStage(**v) for k, v in by_topic.items()},
        by_intent={k: FunnelStage(**v) for k, v in by_intent.items()},
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
                # Mask PII by default like every other free-text admin field — a model
                # summary can echo an email/phone the visitor typed (contracts §10, #12).
                summary=mask_pii_in_text(c.summary.tldr) if c.summary else None,
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
        # Masked by default (the summary is derived from the transcript, which is masked
        # right below); the unmasked transcript is only via the audited reveal endpoint.
        summary=mask_pii_in_text(conversation.summary.tldr) if conversation.summary else None,
        key_points=(
            [mask_pii_in_text(p) for p in conversation.summary.key_points]
            if conversation.summary
            else []
        ),
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


# --- Knowledge management (V1.5; admin role, audited). Provider ids never exposed (#6). ---


class KnowledgeSummary(BaseModel):
    source_id: str
    title: str
    category: str
    approved: bool
    lifecycle: str
    indexing_status: str
    version: str
    owner: str
    review_date: datetime | None
    updated_at: datetime


class KnowledgeListResponse(BaseModel):
    sources: list[KnowledgeSummary]


def _knowledge_summary(s: KnowledgeSource) -> KnowledgeSummary:
    # NEVER expose openai_file_id / vector_store_id to the browser (invariant #6).
    return KnowledgeSummary(
        source_id=s.id,
        title=s.title,
        category=s.category,
        approved=s.approved,
        lifecycle=s.lifecycle,
        indexing_status=s.indexing_status,
        version=s.version,
        owner=s.owner,
        review_date=s.review_date,
        updated_at=s.updated_at,
    )


async def _read_upload(file: UploadFile) -> bytes:
    # Read at most the cap (+1 to detect overflow) so a large part can't materialize
    # unbounded in memory here — independent of the global Content-Length guard, which
    # covers the pre-parse spool. Together they bound both memory and disk.
    content = await file.read(_MAX_KNOWLEDGE_BYTES + 1)
    if not content:
        raise AppError(ErrorCode.INVALID_REQUEST, "The uploaded file is empty.")
    if len(content) > _MAX_KNOWLEDGE_BYTES:
        raise AppError(ErrorCode.PAYLOAD_TOO_LARGE, "The uploaded file is too large.")
    return content


async def _record_upload(
    store: KnowledgeStore,
    knowledge: KnowledgeRepoDep,
    *,
    source_id: str,
    filename: str,
    content: bytes,
    title: str,
    category: str,
) -> KnowledgeSource:
    """Store the bytes + record governance metadata under a caller-supplied ``source_id``
    (so the caller can write the audit record first). NOT attached to the store yet — a
    source only becomes searchable on approve (so unapproved content is never served)."""
    try:
        file_id = await store.upload(filename=filename, content=content)
    except KnowledgeStoreError as exc:
        raise AppError(
            ErrorCode.INTERNAL_ERROR, "Knowledge upload failed.", retryable=exc.retryable
        ) from None
    return await knowledge.record_source(
        source_id=source_id,
        openai_file_id=file_id,
        vector_store_id=get_settings().openai_vector_store_id or "simulated",
        title=title,
        category=category,
        approved=False,
        lifecycle="active",
        indexing_status="pending",  # awaiting approval → attach → index
        source_url=f"/knowledge/{source_id}",
        checksum=hashlib.sha256(content).hexdigest(),
    )


@router.get("/knowledge-sources", response_model=KnowledgeListResponse)
async def list_knowledge_sources(
    _admin: AdminDep, knowledge: KnowledgeRepoDep
) -> KnowledgeListResponse:
    return KnowledgeListResponse(
        sources=[_knowledge_summary(s) for s in await knowledge.list_sources()]
    )


@router.post("/knowledge-sources", response_model=KnowledgeSummary)
async def upload_knowledge(
    admin: AdminRoleDep,
    knowledge: KnowledgeRepoDep,
    store: KnowledgeStoreDep,
    audit: AuditRepoDep,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1, max_length=200)],
    reason: Annotated[str, Form(min_length=1, max_length=500)],
    category: Annotated[str, Form(max_length=100)] = "general",
) -> KnowledgeSummary:
    """Upload a knowledge file (admin only, audited). It is stored but NOT searchable
    until approved — approve attaches it to the Vector Store."""
    content = await _read_upload(file)
    source_id = ids.knowledge_source_id()
    # Audit BEFORE the store write (codebase convention): a failed audit must never
    # leave an un-audited content action.
    await audit.record(
        actor=admin.username,
        role=admin.role,
        action="upload_knowledge",
        target_type="knowledge_source",
        target_id=source_id,
        reason=reason,
    )
    source = await _record_upload(
        store,
        knowledge,
        source_id=source_id,
        filename=file.filename or "upload.md",
        content=content,
        title=title,
        category=category,
    )
    return _knowledge_summary(source)


@router.post("/knowledge-sources/{source_id}/approve", response_model=KnowledgeSummary)
async def approve_knowledge(
    source_id: str,
    body: ReasonBody,
    admin: AdminRoleDep,
    knowledge: KnowledgeRepoDep,
    store: KnowledgeStoreDep,
    jobs: JobRepoDep,
    audit: AuditRepoDep,
) -> KnowledgeSummary:
    """Approve a source: ATTACH it to the Vector Store so retrieval serves it, then poll
    indexing to completion (admin only, audited)."""
    source = await knowledge.get(source_id)
    if source is None or source.lifecycle != "active" or source.openai_file_id is None:
        raise AppError(ErrorCode.INVALID_REQUEST, "No active knowledge source to approve.")
    # Audit BEFORE attaching (which makes the file searchable): approve is the serving
    # gate, so a failed audit must never leave served-but-un-audited content (#12).
    await audit.record(
        actor=admin.username,
        role=admin.role,
        action="approve_knowledge",
        target_type="knowledge_source",
        target_id=source_id,
        reason=body.reason,
    )
    try:
        indexing = await store.attach(
            source.openai_file_id,
            attributes={
                "source_id": source.id,
                "title": source.title[:512],
                "category": source.category[:512],
                "display_url": (source.source_url or f"/knowledge/{source.id}")[:512],
            },
        )
    except KnowledgeStoreError as exc:
        raise AppError(
            ErrorCode.INTERNAL_ERROR, "Attaching to the store failed.", retryable=exc.retryable
        ) from None
    await knowledge.set_approved(source_id, approved=True)
    await knowledge.update_indexing_status(source_id, indexing)
    if indexing == "pending":
        # Generous attempt budget: with the capped backoff this re-polls for ~45 min,
        # so a healthy-but-slow index never dead-letters (invariant: safe under retry).
        await jobs.enqueue(
            "poll_indexing",
            resource_id=source_id,
            max_attempts=get_settings().knowledge_index_poll_attempts,
        )
    updated = await knowledge.get(source_id)
    assert updated is not None
    return _knowledge_summary(updated)


@router.post("/knowledge-sources/{source_id}/remove", response_model=KnowledgeSummary)
async def remove_knowledge(
    source_id: str,
    body: ReasonBody,
    admin: AdminRoleDep,
    knowledge: KnowledgeRepoDep,
    store: KnowledgeStoreDep,
    audit: AuditRepoDep,
) -> KnowledgeSummary:
    """Unpublish a source: DETACH it from the Vector Store (stops retrieval) + mark it
    removed (admin only, audited)."""
    source = await knowledge.get(source_id)
    if source is None or source.lifecycle == "removed":
        raise AppError(ErrorCode.INVALID_REQUEST, "No knowledge source to remove.")
    # Audit BEFORE detaching (which stops serving): a failed audit must never leave an
    # un-audited content-removal action (#12).
    await audit.record(
        actor=admin.username,
        role=admin.role,
        action="remove_knowledge",
        target_type="knowledge_source",
        target_id=source_id,
        reason=body.reason,
    )
    # Only an APPROVED source is attached to the store; detaching an unapproved
    # (never-attached) file would 404 on the real store. approved ⟺ attached.
    if source.openai_file_id and source.approved:
        try:
            await store.detach(source.openai_file_id)
        except KnowledgeStoreError as exc:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                "Detaching from the store failed.",
                retryable=exc.retryable,
            ) from None
    await knowledge.set_lifecycle(source_id, "removed")
    await knowledge.set_approved(source_id, approved=False)
    updated = await knowledge.get(source_id)
    assert updated is not None
    return _knowledge_summary(updated)


@router.post("/knowledge-sources/{source_id}/replace", response_model=KnowledgeSummary)
async def replace_knowledge(
    source_id: str,
    admin: AdminRoleDep,
    knowledge: KnowledgeRepoDep,
    store: KnowledgeStoreDep,
    audit: AuditRepoDep,
    file: Annotated[UploadFile, File()],
    reason: Annotated[str, Form(min_length=1, max_length=500)],
) -> KnowledgeSummary:
    """Replace a source's file: upload the new one (unapproved, awaiting approval), then
    detach + retire the old (admin only, audited)."""
    old = await knowledge.get(source_id)
    if old is None or old.lifecycle != "active":
        raise AppError(ErrorCode.INVALID_REQUEST, "No active knowledge source to replace.")
    content = await _read_upload(file)
    new_source_id = ids.knowledge_source_id()
    # Audit BEFORE the mutations (which retire the served old source): a failed audit
    # must never leave an un-audited content-replace action (#12).
    await audit.record(
        actor=admin.username,
        role=admin.role,
        action="replace_knowledge",
        target_type="knowledge_source",
        target_id=source_id,
        reason=reason,
    )
    new = await _record_upload(
        store,
        knowledge,
        source_id=new_source_id,
        filename=file.filename or "upload.md",
        content=content,
        title=old.title,
        category=old.category,
    )
    # Only detach an APPROVED (attached) old source; an unapproved one was never in
    # the store, so detaching it would 404 on the real store. approved ⟺ attached.
    if old.openai_file_id and old.approved:
        try:
            await store.detach(old.openai_file_id)
        except KnowledgeStoreError:
            # Non-fatal: the new record exists; the old file can be cleaned via remove.
            logger.warning(
                "knowledge.replace.detach_failed", extra={"context": {"source_id": source_id}}
            )
    await knowledge.set_lifecycle(source_id, "replaced")
    return _knowledge_summary(new)


def _to_report_response(report: InsightsReport) -> InsightsReportResponse:
    return InsightsReportResponse(
        period_type=report.period_type,
        period_key=report.period_key,
        generated_at=report.generated_at,
        window_start=report.window_start,
        window_end=report.window_end,
        conversations_analyzed=report.conversations_analyzed,
        conversations_in_period=report.conversations_in_period,
        summary=report.summary,
        clusters=[
            InsightsCluster(
                # Cluster questions are verbatim visitor text → mask by default like every
                # other admin free-text (unresolved questions, summaries). Reveal stays the
                # audited per-record path (contracts §10, invariant #12). `label` is masked
                # too: it falls back to the raw representative question when the analyze LLM
                # call times out / returns no label (service.py `_analyze`/`_parse_analysis`).
                label=mask_pii_in_text(c.label),
                representative_question=mask_pii_in_text(c.representative_question),
                sample_questions=[mask_pii_in_text(q) for q in c.sample_questions],
                size=c.size,
                dominant_topic=c.dominant_topic,
                coverage=c.coverage,
                conversation_ids=c.conversation_ids,
                proposed_question=(mask_pii_in_text(c.proposed.question) if c.proposed else None),
                proposed_answer=c.proposed.answer if c.proposed else None,
                proposed_canonical_intent=(
                    c.proposed.canonical_draft_intent if c.proposed else None
                ),
            )
            for c in report.clusters
        ],
    )


@router.get("/insights", response_model=InsightsLatestResponse)
async def latest_insights(_admin: AdminDep, insights: InsightsRepoDep) -> InsightsLatestResponse:
    """The most recent insights report (any horizon), for the admin Insights view."""
    report = await insights.latest()
    return InsightsLatestResponse(
        report=_to_report_response(report) if report is not None else None
    )


@router.get("/insights/reports", response_model=InsightsListResponse)
async def list_insights(_admin: AdminDep, insights: InsightsRepoDep) -> InsightsListResponse:
    """Recent reports (newest first) so the UI can offer a day/week/month picker."""
    return InsightsListResponse(
        reports=[
            InsightsReportItem(
                report_id=r.id,
                period_type=r.period_type,
                period_key=r.period_key,
                generated_at=r.generated_at,
                conversations_analyzed=r.conversations_analyzed,
                cluster_count=len(r.clusters),
            )
            for r in await insights.list_recent()
        ]
    )


@router.get("/insights/gaps", response_model=KnowledgeGapsResponse)
async def insights_gaps(
    _admin: AdminDep,
    insights: InsightsRepoDep,
    window: Annotated[int, Query(ge=1, le=90)] = 14,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> KnowledgeGapsResponse:
    """Ranked knowledge gaps: the non-covered question themes aggregated across the last
    ``window`` DAILY reports, biggest / most-persistent first. A read-side view over stored
    reports — no model calls. Question text is masked (contracts §10); reveal stays the
    audited per-record path. Daily only, so overlapping weekly/monthly can't double-count."""
    reports = await insights.list_recent(limit=window, period_type="daily")
    gaps = rank_gaps(reports, limit=limit)
    return KnowledgeGapsResponse(
        window_days=window,
        daily_reports=len(reports),
        gaps=[
            KnowledgeGapItem(
                # `key`/`label` can embed the raw representative question (the analyze-LLM
                # fallback — see `_to_report_response`), so mask them like the question fields.
                key=mask_pii_in_text(g.key),
                label=mask_pii_in_text(g.label),
                representative_question=mask_pii_in_text(g.representative_question),
                coverage=g.coverage,
                total_asked=g.total_asked,
                days_seen=g.days_seen,
                proposed_question=(
                    mask_pii_in_text(g.proposed_question) if g.proposed_question else None
                ),
                proposed_answer=g.proposed_answer,
                proposed_canonical_intent=g.canonical_draft_intent,
                last_period_key=g.last_period_key,
                last_generated_at=g.last_generated_at,
            )
            for g in gaps
        ],
    )


@router.get("/insights/reports/{report_id}", response_model=InsightsReportResponse)
async def get_insights_report(
    report_id: str, _admin: AdminDep, insights: InsightsRepoDep
) -> InsightsReportResponse:
    report = await insights.get(report_id)
    if report is None:
        raise AppError(ErrorCode.CONVERSATION_NOT_FOUND, "Insights report not found.")
    return _to_report_response(report)


@router.post("/insights/run", response_model=ActionResponse)
async def run_insights_now(
    admin: AdminRoleDep, jobs: JobRepoDep, audit: AuditRepoDep
) -> ActionResponse:
    """Queue an on-demand insights run (regenerates the current in-progress periods).
    Admin-only + audited; the worker does the work asynchronously (spends model $)."""
    # Dedup rapid/duplicate clicks: only enqueue when no manual refresh is already pending
    # or running (matched by the "refresh" resource id, so a scheduled run doesn't block it).
    if not await jobs.has_active_for_resource("generate_insights", "refresh"):
        await jobs.enqueue("generate_insights", resource_id="refresh")
        detail = "Insights run queued."
    else:
        detail = "An insights run is already in progress."
    await audit.record(
        actor=admin.username,
        role=admin.role,
        action="run_insights",
        target_type="insights",
        target_id="refresh",
        reason="manual insights run",
    )
    return ActionResponse(ok=True, detail=detail)


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
