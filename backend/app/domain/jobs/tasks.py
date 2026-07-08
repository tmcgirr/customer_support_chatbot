"""Periodic maintenance tasks run by the worker (via job handlers).

Each is idempotent and repo-level so it can be unit-tested without the worker.
None touch message content or PII — they operate on counts, timestamps, and
local IDs (CLAUDE.md invariant #5).
"""

from datetime import UTC, datetime, timedelta

from app.domain.aggregates.repository import AggregatesRepository
from app.domain.conversations.repository import ConversationRepository
from app.domain.feedback.repository import FeedbackRepository
from app.domain.jobs.repository import JobRepository
from app.domain.knowledge.repository import KnowledgeSourceRepository
from app.domain.requests.repository import RequestRepository


def _now() -> datetime:
    return datetime.now(UTC)


async def run_stale_lock_sweep(repo: ConversationRepository, lock_stale_seconds: int) -> int:
    """Release conversation run-locks leaked by a crashed turn."""
    return await repo.clear_stale_locks(_now() - timedelta(seconds=lock_stale_seconds))


async def run_abandonment_sweep(repo: ConversationRepository, abandon_seconds: int) -> int:
    """Mark long-inactive active conversations abandoned (feeds outcome metrics)."""
    return await repo.mark_abandoned(_now() - timedelta(seconds=abandon_seconds))


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
