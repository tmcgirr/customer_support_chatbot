"""Periodic maintenance tasks run by the worker (via job handlers).

Each is idempotent and repo-level so it can be unit-tested without the worker.
None touch message content or PII — they operate on counts, timestamps, and
local IDs (CLAUDE.md invariant #5).
"""

from datetime import UTC, datetime, timedelta

from app.domain.aggregates.repository import AggregatesRepository
from app.domain.audit.repository import AuditRepository
from app.domain.conversations.repository import (
    REQUEST_CONVERSION_OUTCOMES,
    ConversationRepository,
)
from app.domain.feedback.repository import FeedbackRepository
from app.domain.jobs.repository import JobRepository
from app.domain.knowledge.repository import KnowledgeSourceRepository
from app.domain.knowledge.store import KnowledgeStore, KnowledgeStoreError
from app.domain.privacy.repository import PrivacyRequestRepository
from app.domain.requests.repository import RequestRepository


def _now() -> datetime:
    return datetime.now(UTC)


async def run_stale_lock_sweep(repo: ConversationRepository, lock_stale_seconds: int) -> int:
    """Release conversation run-locks leaked by a crashed turn."""
    return await repo.clear_stale_locks(_now() - timedelta(seconds=lock_stale_seconds))


async def run_abandonment_sweep(
    repo: ConversationRepository, abandon_seconds: int, *, anonymous_ttl_seconds: int
) -> int:
    """Mark long-inactive active conversations abandoned (feeds outcome metrics) and
    stamp the anonymous-retention TTL on the walk-aways (V6)."""
    return await repo.mark_abandoned(
        _now() - timedelta(seconds=abandon_seconds), anonymous_ttl_seconds=anonymous_ttl_seconds
    )


async def run_knowledge_review_reminder(repo: KnowledgeSourceRepository) -> list[str]:
    """Return the local ids of active sources past their review_date (for the
    admin knowledge UI to surface in V5). IDs only — no content."""
    due = await repo.list_due_for_review(_now())
    return [source.id for source in due]


async def run_daily_aggregates(
    conversations: ConversationRepository,
    requests: RequestRepository,
    feedback: FeedbackRepository,
    aggregates: AggregatesRepository,
) -> dict[str, object]:
    """Snapshot conversation/request/feedback counts for today's UTC date."""
    payload: dict[str, object] = {
        "conversations": {
            "total": await conversations.total(),
            "by_status": await conversations.count_by("status"),
            "by_outcome": await conversations.count_by("outcome"),
        },
        "requests": {
            "total": await requests.total(),
            "by_type": await requests.count_by("type"),
            "by_status": await requests.count_by("status"),
        },
        "feedback": {
            "total": await feedback.total(),
            "by_rating": await feedback.count_by("rating"),
        },
    }
    date_key = _now().date().isoformat()
    await aggregates.record_daily(date_key, payload)
    return payload


async def run_retention_sweep(
    conversations: ConversationRepository,
    requests: RequestRepository,
    feedback: FeedbackRepository,
    privacy: PrivacyRequestRepository,
    *,
    abandoned_conversation_days: int,
    conversation_days: int,
    request_days: int,
    feedback_days: int,
    privacy_request_days: int,
    batch: int,
) -> dict[str, int]:
    """Enforce retention classes: hard-delete data past its period across every
    collection (contracts §8, invariant #13). Aggregates already snapshot the counts,
    so metrics survive. Each delete is bounded by ``batch`` so no run takes an
    unbounded lock; the daily cadence drains a backlog over successive runs.
    Conversations are deleted by last_activity (so a converted one outlives its
    request), requests/feedback by created_at. Returns per-class counts (no PII)."""
    now = _now()
    return {
        "conversations_abandoned": await conversations.delete_before(
            now - timedelta(days=abandoned_conversation_days),
            limit=batch,
            statuses=["abandoned"],
            # Never reap a converted conversation at the short anonymous period — it
            # lives with its request until the long backstop below (no orphaned request).
            exclude_outcomes=list(REQUEST_CONVERSION_OUTCOMES),
        ),
        "conversations_expired": await conversations.delete_before(
            now - timedelta(days=conversation_days), limit=batch
        ),
        "requests": await requests.delete_before(now - timedelta(days=request_days), limit=batch),
        "feedback": await feedback.delete_before(now - timedelta(days=feedback_days), limit=batch),
        "privacy_requests": await privacy.delete_before(
            now - timedelta(days=privacy_request_days), limit=batch
        ),
    }


async def run_privacy_delete(
    privacy: PrivacyRequestRepository,
    requests: RequestRepository,
    conversations: ConversationRepository,
    feedback: FeedbackRepository,
    audit: AuditRepository,
    *,
    privacy_request_id: str,
) -> dict[str, int]:
    """Execute a VERIFIED subject-erasure request (privacy_delete job). Redacts the
    subject's requests + conversations to tombstones and drops their feedback, then
    records an audit entry and marks the request completed. Idempotent: a replay of
    an already-completed request is a no-op; the redactions are match-and-skip.

    Subject scope = the named conversation (if any) plus every request matching the
    requester's email and each of those requests' conversations."""
    pvr = await privacy.get(privacy_request_id)
    if pvr is None or pvr.verification_status != "verified":
        return {}  # gone, or never verified — never delete on an unverified request
    if pvr.status != "open":
        return pvr.result_counts or {}  # already completed/failed → replay no-op

    matched = await requests.find_by_email(pvr.requester_email)
    # Scope conversations to those the requester provably owns: the conversations of
    # requests bearing their (verified) email. We do NOT add pvr.conversation_id blindly
    # — it arrives from the unauthenticated public endpoint and, for an anonymous
    # transcript, cannot be proven to belong to this subject by email alone; honoring it
    # would let a verified requester erase someone ELSE's named conversation. An
    # unlinked transcript is left for the operator to handle via the audited admin path
    # (documented limitation). A named conversation that IS the subject's already appears
    # here via its matched request.
    conversation_ids = {r.conversation_id for r in matched}
    conv_id_list = list(conversation_ids)
    counts = {
        "requests": await requests.redact_for_deletion([r.id for r in matched]),
        "conversations": await conversations.redact_for_deletion(conv_id_list),
        "feedback": await feedback.delete_for_conversations(conv_id_list),
    }
    # Audit BEFORE marking complete: an erasure must never be unrecorded (invariant
    # #12). A rare retry between here and the guarded mark_completed may double-record,
    # which is benign and visible — the safer direction than a lost record.
    await audit.record(
        actor=pvr.verified_by or "system",
        role="admin",
        action="delete",
        target_type="privacy_request",
        target_id=pvr.id,
        reason=f"subject erasure counts={counts}",
    )
    await privacy.mark_completed(pvr.id, result_counts=counts)
    return counts


async def run_privacy_reconcile(
    privacy: PrivacyRequestRepository,
    jobs: JobRepository,
    *,
    stuck_after_seconds: int,
) -> int:
    """Re-enqueue verified deletion requests that are still open but have no active
    privacy_delete job — i.e. the enqueue was lost (crash between verify-commit and
    enqueue). Bounded lookback so a just-verified request isn't raced. A dead-lettered
    erasure is already marked ``failed`` (not open), so it is not re-enqueued here.
    Returns the count re-enqueued (invariant #13: a verified erasure always runs)."""
    cutoff = _now() - timedelta(seconds=stuck_after_seconds)
    reenqueued = 0
    for pvr in await privacy.list_verified_open(verified_before=cutoff):
        if await jobs.has_active_for_resource("privacy_delete", pvr.id):
            continue
        await jobs.enqueue("privacy_delete", resource_id=pvr.id)
        reenqueued += 1
    return reenqueued


async def run_poll_indexing(
    knowledge: KnowledgeSourceRepository,
    store: KnowledgeStore,
    *,
    source_id: str,
) -> dict[str, str]:
    """Poll a just-uploaded knowledge file's indexing status and record it. While it is
    still ``pending`` the job RAISES (retryable) so the worker re-polls with backoff;
    once ``indexed``/``failed`` it returns. Idempotent: a gone/terminal/inactive source
    is a no-op."""
    source = await knowledge.get(source_id)
    if source is None or source.openai_file_id is None:
        return {"status": "gone"}
    if source.lifecycle != "active":
        # Removed/replaced after approval: the file was DETACHED, so polling its
        # status would 404 and dead-letter uselessly. Stop — there's nothing to poll.
        return {"status": "inactive"}
    if source.indexing_status in ("indexed", "failed"):
        return {"status": source.indexing_status}
    status = await store.status(source.openai_file_id)
    await knowledge.update_indexing_status(source_id, status)
    if status == "pending":
        # Not done yet — retry the job (bounded by max_attempts) to re-poll.
        raise KnowledgeStoreError("still_indexing", retryable=True)
    return {"status": status}


async def run_reconcile_deliveries(
    requests: RequestRepository,
    jobs: JobRepository,
    *,
    stuck_after_seconds: int,
    enable_delivery: bool,
) -> dict[str, int]:
    """Reconcile requests whose delivery job terminated without parking them (worker
    crash, timeout, lost enqueue): a stuck ``delivering`` with no active job → park
    ``delivery_failed``; a ``received`` with no job (lost enqueue) → re-enqueue.
    Requests with an active delivery job are left alone."""
    cutoff = _now() - timedelta(seconds=stuck_after_seconds)
    reenqueued = parked = 0
    for record in await requests.list_undelivered(cutoff):
        if await jobs.has_active_for_resource("deliver_request", record.id):
            continue  # still being delivered/retried
        if record.status == "delivering":
            await requests.mark_delivery_failed(record.id, "orphaned_delivery")
            parked += 1
        elif record.status == "received" and enable_delivery:
            await jobs.enqueue("deliver_request", resource_id=record.id)
            reenqueued += 1
    return {"parked": parked, "reenqueued": reenqueued}
