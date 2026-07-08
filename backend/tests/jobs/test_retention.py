"""V6 retention + subject-erasure task tests, run directly against MongoDB.

Covers the two checkpoint mechanisms: the periodic retention sweep (deletes data
past its class period, keeps recent) and the verified deletion (purges a subject
across every collection, audited, idempotent, and scoped to that subject only)."""

from datetime import UTC, datetime, timedelta

from app.domain.audit.repository import AuditRepository
from app.domain.conversations.repository import ConversationRepository
from app.domain.feedback.models import Feedback
from app.domain.feedback.repository import FeedbackRepository
from app.domain.jobs.repository import JobRepository
from app.domain.jobs.tasks import run_privacy_delete, run_privacy_reconcile, run_retention_sweep
from app.domain.privacy.repository import PrivacyRequestRepository
from app.domain.requests.models import Contact, RequestRecord
from app.domain.requests.repository import RequestRepository
from tests.jobs.conftest import Database


def _now() -> datetime:
    return datetime.now(UTC)


async def _make_request(
    requests: RequestRepository, *, email: str, conversation_id: str, created_at: datetime
) -> str:
    rid = f"req_{email}_{conversation_id}"
    await requests._collection.insert_one(  # type: ignore[attr-defined]
        RequestRecord(
            id=rid,
            type="strategy_call",
            conversation_id=conversation_id,
            idempotency_key=f"key_{rid}",
            reference="REF",
            contact=Contact(name="Ada", email=email, company="Acme"),
            fields={"reason": "exploring"},
            consent_version="c",
            created_at=created_at,
        ).model_dump(by_alias=True)
    )
    return rid


# --- Retention sweep ---


async def test_retention_sweep_deletes_past_period_keeps_recent(db: Database) -> None:
    convos = ConversationRepository(db["conversations"])
    requests = RequestRepository(db["requests"])
    feedback = FeedbackRepository(db["feedback"])
    privacy = PrivacyRequestRepository(db["privacy_requests"])

    old = _now() - timedelta(days=400)
    recent = _now() - timedelta(days=10)
    # Old conversation (past 365d) + recent one.
    old_convo = await convos.create()
    await db["conversations"].update_one({"_id": old_convo.id}, {"$set": {"last_activity_at": old}})
    recent_convo = await convos.create()
    # Old + recent request.
    await _make_request(requests, email="a@x.com", conversation_id="cnv_old", created_at=old)
    await _make_request(requests, email="b@x.com", conversation_id="cnv_new", created_at=recent)
    # Old + recent feedback.
    for cid, when in (("cnv_old", old), ("cnv_new", recent)):
        await feedback.record(
            Feedback(
                id=f"fbk_{cid}",
                conversation_id=cid,
                message_id="m",
                rating="helpful",
                created_at=when,
            )
        )

    counts = await run_retention_sweep(
        convos,
        requests,
        feedback,
        privacy,
        abandoned_conversation_days=30,
        conversation_days=365,
        request_days=365,
        feedback_days=365,
        privacy_request_days=730,
        batch=500,
    )
    assert counts["conversations_expired"] == 1
    assert counts["requests"] == 1
    assert counts["feedback"] == 1
    # Recent survives.
    assert await db["conversations"].count_documents({"_id": recent_convo.id}) == 1
    assert await db["requests"].count_documents({"contact.email": "b@x.com"}) == 1
    assert await db["feedback"].count_documents({"conversation_id": "cnv_new"}) == 1


async def test_retention_sweep_batch_bounds_deletes(db: Database) -> None:
    requests = RequestRepository(db["requests"])
    old = _now() - timedelta(days=400)
    for i in range(5):
        await _make_request(requests, email=f"e{i}@x.com", conversation_id=f"c{i}", created_at=old)
    deleted = await requests.delete_before(_now() - timedelta(days=365), limit=2)
    assert deleted == 2  # bounded per run
    assert await db["requests"].count_documents({}) == 3


async def test_converted_conversation_gets_no_anonymous_ttl(db: Database) -> None:
    convos = ConversationRepository(db["conversations"])
    convo = await convos.create()
    # Inactive AND converted (a request was created) → must NOT get an expire_at.
    await db["conversations"].update_one(
        {"_id": convo.id},
        {
            "$set": {
                "last_activity_at": _now() - timedelta(days=2),
                "outcome": "strategy_call_requested",
            }
        },
    )
    marked = await convos.mark_abandoned(
        _now() - timedelta(days=1), anonymous_ttl_seconds=30 * 86_400
    )
    assert marked == 1
    doc = await db["conversations"].find_one({"_id": convo.id})
    assert doc is not None and doc["status"] == "abandoned" and doc.get("expire_at") is None


# --- Verified subject erasure ---


async def _seed_subject(
    convos: ConversationRepository,
    requests: RequestRepository,
    feedback: FeedbackRepository,
    *,
    email: str,
    conversation_id: str,
) -> None:
    await db_insert_conversation(convos, conversation_id, email)
    await _make_request(requests, email=email, conversation_id=conversation_id, created_at=_now())
    await feedback.record(
        Feedback(
            id=f"fbk_{conversation_id}",
            conversation_id=conversation_id,
            message_id="m",
            rating="not_helpful",
            comment=f"reach me at {email}",
            created_at=_now(),
        )
    )


async def db_insert_conversation(
    convos: ConversationRepository, conversation_id: str, email: str
) -> None:
    from app.domain.conversations.models import Conversation, Message

    convo = Conversation(
        id=conversation_id,
        started_at=_now(),
        last_activity_at=_now(),
        messages=[
            Message(id="msg_1", role="user", content=f"my email is {email}", created_at=_now())
        ],
    )
    await convos._collection.insert_one(convo.model_dump(by_alias=True))  # type: ignore[attr-defined]


async def test_privacy_delete_purges_subject_across_collections_and_audits(db: Database) -> None:
    convos = ConversationRepository(db["conversations"])
    requests = RequestRepository(db["requests"])
    feedback = FeedbackRepository(db["feedback"])
    privacy = PrivacyRequestRepository(db["privacy_requests"])
    audit = AuditRepository(db["audit"])

    await _seed_subject(convos, requests, feedback, email="target@x.com", conversation_id="cnv_t")
    # A DIFFERENT subject that must be untouched.
    await _seed_subject(convos, requests, feedback, email="other@x.com", conversation_id="cnv_o")

    pvr = await privacy.create(
        request_type="deletion", requester_email="target@x.com", conversation_id="cnv_t"
    )
    await privacy.mark_verified(pvr.id, verified_by="admin")

    counts = await run_privacy_delete(
        privacy, requests, convos, feedback, audit, privacy_request_id=pvr.id
    )
    assert counts == {"requests": 1, "conversations": 1, "feedback": 1}

    # Target conversation is a redacting tombstone: no messages, status deleted.
    conv = await db["conversations"].find_one({"_id": "cnv_t"})
    assert conv is not None and conv["status"] == "deleted" and conv["messages"] == []
    # Target request contact PII stripped.
    req = await db["requests"].find_one({"conversation_id": "cnv_t"})
    assert req is not None and req["contact"]["email"] is None and req["fields"] == {}
    # Target feedback dropped.
    assert await db["feedback"].count_documents({"conversation_id": "cnv_t"}) == 0

    # Other subject fully intact.
    other = await db["conversations"].find_one({"_id": "cnv_o"})
    assert other is not None and other["status"] != "deleted" and other["messages"] != []
    other_req = await db["requests"].find_one({"conversation_id": "cnv_o"})
    assert other_req is not None and other_req["contact"]["email"] == "other@x.com"
    assert await db["feedback"].count_documents({"conversation_id": "cnv_o"}) == 1

    # Audited + request completed.
    assert await db["audit"].count_documents({"action": "delete", "target_id": pvr.id}) == 1
    done = await privacy.get(pvr.id)
    assert done is not None and done.status == "completed" and done.result_counts == counts


async def test_privacy_delete_is_idempotent(db: Database) -> None:
    convos = ConversationRepository(db["conversations"])
    requests = RequestRepository(db["requests"])
    feedback = FeedbackRepository(db["feedback"])
    privacy = PrivacyRequestRepository(db["privacy_requests"])
    audit = AuditRepository(db["audit"])

    await _seed_subject(convos, requests, feedback, email="t@x.com", conversation_id="cnv_t")
    pvr = await privacy.create(
        request_type="deletion", requester_email="t@x.com", conversation_id="cnv_t"
    )
    await privacy.mark_verified(pvr.id, verified_by="admin")

    first = await run_privacy_delete(
        privacy, requests, convos, feedback, audit, privacy_request_id=pvr.id
    )
    second = await run_privacy_delete(
        privacy, requests, convos, feedback, audit, privacy_request_id=pvr.id
    )
    assert first == {"requests": 1, "conversations": 1, "feedback": 1}
    assert second == first  # replay returns stored counts, no-op
    # Exactly one audit + one completion despite the replay.
    assert await db["audit"].count_documents({"target_id": pvr.id}) == 1


async def test_privacy_delete_does_not_erase_unowned_named_conversation(db: Database) -> None:
    # HIGH review finding: a subject-supplied conversation_id must NOT be erased unless it
    # is provably the subject's (linked by a request bearing the verified email).
    convos = ConversationRepository(db["conversations"])
    requests = RequestRepository(db["requests"])
    feedback = FeedbackRepository(db["feedback"])
    privacy = PrivacyRequestRepository(db["privacy_requests"])
    audit = AuditRepository(db["audit"])

    # A victim conversation belonging to someone else (no request for the requester).
    await db_insert_conversation(convos, "cnv_victim", "victim@x.com")
    # The requester has NO requests at all, but names the victim's conversation.
    pvr = await privacy.create(
        request_type="deletion", requester_email="attacker@x.com", conversation_id="cnv_victim"
    )
    await privacy.mark_verified(pvr.id, verified_by="admin")

    counts = await run_privacy_delete(
        privacy, requests, convos, feedback, audit, privacy_request_id=pvr.id
    )
    # Nothing owned by the requester → nothing erased; the victim is untouched.
    assert counts == {"requests": 0, "conversations": 0, "feedback": 0}
    victim = await db["conversations"].find_one({"_id": "cnv_victim"})
    assert victim is not None and victim["status"] != "deleted" and victim["messages"] != []


async def test_privacy_reconcile_reenqueues_lost_erasure(db: Database) -> None:
    # MEDIUM review finding: a verified erasure whose enqueue was lost is recovered.
    privacy = PrivacyRequestRepository(db["privacy_requests"])
    jobs = JobRepository(db["jobs"])
    pvr = await privacy.create(
        request_type="deletion", requester_email="t@x.com", conversation_id=None
    )
    await privacy.mark_verified(pvr.id, verified_by="admin")
    # Backdate the verify so it's outside the reconcile lookback (no job was enqueued).
    await db["privacy_requests"].update_one(
        {"_id": pvr.id}, {"$set": {"verified_at": _now() - timedelta(hours=1)}}
    )
    reenqueued = await run_privacy_reconcile(privacy, jobs, stuck_after_seconds=900)
    assert reenqueued == 1
    assert await db["jobs"].count_documents({"type": "privacy_delete", "resource_id": pvr.id}) == 1
    # Idempotent: a second run sees the active job and does not double-enqueue.
    assert await run_privacy_reconcile(privacy, jobs, stuck_after_seconds=900) == 0


async def test_privacy_reconcile_ignores_completed_and_recent(db: Database) -> None:
    privacy = PrivacyRequestRepository(db["privacy_requests"])
    jobs = JobRepository(db["jobs"])
    # A just-verified request (inside the lookback) is not raced.
    fresh = await privacy.create(
        request_type="deletion", requester_email="a@x.com", conversation_id=None
    )
    await privacy.mark_verified(fresh.id, verified_by="admin")
    # A completed one is never re-enqueued.
    done = await privacy.create(
        request_type="deletion", requester_email="b@x.com", conversation_id=None
    )
    await privacy.mark_verified(done.id, verified_by="admin")
    await db["privacy_requests"].update_one(
        {"_id": done.id},
        {"$set": {"status": "completed", "verified_at": _now() - timedelta(hours=1)}},
    )
    assert await run_privacy_reconcile(privacy, jobs, stuck_after_seconds=900) == 0


async def test_privacy_delete_skips_unverified(db: Database) -> None:
    convos = ConversationRepository(db["conversations"])
    requests = RequestRepository(db["requests"])
    feedback = FeedbackRepository(db["feedback"])
    privacy = PrivacyRequestRepository(db["privacy_requests"])
    audit = AuditRepository(db["audit"])

    await _seed_subject(convos, requests, feedback, email="t@x.com", conversation_id="cnv_t")
    pvr = await privacy.create(
        request_type="deletion", requester_email="t@x.com", conversation_id="cnv_t"
    )
    # NOT verified.
    counts = await run_privacy_delete(
        privacy, requests, convos, feedback, audit, privacy_request_id=pvr.id
    )
    assert counts == {}
    # Nothing deleted, nothing audited.
    conv = await db["conversations"].find_one({"_id": "cnv_t"})
    assert conv is not None and conv["status"] != "deleted"
    assert await db["audit"].count_documents({}) == 0
