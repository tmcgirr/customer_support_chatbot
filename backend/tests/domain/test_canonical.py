"""Canonical answer repository tests against a real MongoDB.

Self-contained fixture (kept out of the shared conftest): points at the isolated
``cadre_chatbot_test`` database and clears the ``canonical_answers`` collection
around every test. Content is loaded through the real seed builder so the tests
exercise the approved wording that ships (docs 05 §3).
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

from app.core.config import get_settings
from app.domain.canonical.models import CanonicalAnswer
from app.domain.canonical.repository import CanonicalAnswerRepository, ensure_indexes
from scripts.seed_canonical import build_answers

Collection = AsyncIOMotorCollection[dict[str, Any]]

# Isolated from the dev database; created/torn down around each test.
TEST_DB_NAME = "cadre_chatbot_test"


@pytest.fixture
async def canonical_collection() -> AsyncIterator[Collection]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        get_settings().mongo_uri.get_secret_value(), tz_aware=True
    )
    collection = client[TEST_DB_NAME]["canonical_answers"]
    await collection.delete_many({})
    await ensure_indexes(collection)
    try:
        yield collection
    finally:
        await collection.delete_many({})
        client.close()


@pytest.fixture
async def repo(canonical_collection: Collection) -> CanonicalAnswerRepository:
    return CanonicalAnswerRepository(canonical_collection)


@pytest.fixture
async def seeded_repo(repo: CanonicalAnswerRepository) -> CanonicalAnswerRepository:
    for answer in build_answers(datetime.now(UTC)):
        await repo.upsert(answer)
    return repo


async def test_get_canonical_answer_returns_content_and_actions(
    seeded_repo: CanonicalAnswerRepository,
) -> None:
    match = await seeded_repo.get_canonical_answer("pricing")

    assert match.matched is True
    assert match.canonical_answer_id is not None
    assert match.canonical_answer_id.startswith("can_")
    assert match.content is not None
    assert "scoped to the business problem" in match.content
    # Published pricing framing is allowed (invariant #8: served via canonical, not
    # generated); a fabricated fixed consulting fee / hourly rate is not (§7).
    assert "per hour" not in match.content.lower()
    assert "hourly rate" not in match.content.lower()
    assert match.allowed_action_ids == ["strategy_call"]


async def test_data_security_is_mandatory_escalation(
    seeded_repo: CanonicalAnswerRepository,
) -> None:
    match = await seeded_repo.get_canonical_answer("data_security")

    assert match.matched is True
    assert match.mandatory_escalation is True
    assert match.allowed_action_ids == ["human_escalation"]


async def test_unmatched_intent_returns_no_match(
    seeded_repo: CanonicalAnswerRepository,
) -> None:
    match = await seeded_repo.get_canonical_answer("no_such_intent")

    assert match.matched is False
    assert match.canonical_answer_id is None
    assert match.content is None
    assert match.allowed_action_ids == []
    assert match.mandatory_escalation is False


async def test_draft_records_do_not_match(repo: CanonicalAnswerRepository) -> None:
    """Only approved wording is served — a draft yields matched=False."""
    now = datetime.now(UTC)
    await repo.upsert(
        CanonicalAnswer(
            id="can_draft_pricing",
            name="Draft pricing",
            intent="pricing",
            content="Unapproved draft wording.",
            status="draft",
            owner="Sales/Leadership",
            effective_date=now,
            review_date=now,
        )
    )

    match = await repo.get_canonical_answer("pricing")
    assert match.matched is False


async def test_booking_intent_offers_strategy_call_action(
    seeded_repo: CanonicalAnswerRepository,
) -> None:
    # The booking fix: a canonical answer for the strategy_call intent carries the
    # strategy_call action, so a mid-conversation booking reply surfaces the form.
    match = await seeded_repo.get_canonical_answer("strategy_call")
    assert match.matched is True
    assert match.allowed_action_ids == ["strategy_call"]


async def test_approve_promotes_draft_to_served(repo: CanonicalAnswerRepository) -> None:
    now = datetime.now(UTC)
    await repo.upsert(
        CanonicalAnswer(
            id="can_draft_x",
            name="Draft",
            intent="pricing",
            content="new draft wording",
            status="draft",
            owner="Sales",
            effective_date=now,
            review_date=now,
        )
    )
    assert (await repo.get_canonical_answer("pricing")).matched is False  # draft not served
    assert await repo.approve("pricing") is True  # promote
    assert (await repo.get_canonical_answer("pricing")).matched is True  # now served
    assert await repo.approve("pricing") is False  # nothing left in draft


async def test_reseeding_does_not_downgrade_approved(repo: CanonicalAnswerRepository) -> None:
    # H1 guard: `seed --status draft` (or any re-upsert) must update content but
    # NEVER flip an approved answer back to draft — status is set once on insert.
    now = datetime.now(UTC)
    await repo.upsert(
        CanonicalAnswer(
            id="can_a",
            name="X",
            intent="pricing",
            content="approved v1",
            status="approved",
            owner="o",
            effective_date=now,
            review_date=now,
        )
    )
    assert (await repo.get_canonical_answer("pricing")).matched is True
    # Re-upsert the same intent as draft with edited content.
    await repo.upsert(
        CanonicalAnswer(
            id="can_b",
            name="X",
            intent="pricing",
            content="edited v2",
            status="draft",
            owner="o",
            effective_date=now,
            review_date=now,
        )
    )
    match = await repo.get_canonical_answer("pricing")
    assert match.matched is True  # still served — not downgraded
    assert match.content == "edited v2"  # but content did update


async def test_upsert_is_idempotent_by_intent(repo: CanonicalAnswerRepository) -> None:
    """Re-seeding the same intent updates in place and keeps a stable _id."""
    answers = build_answers(datetime.now(UTC))
    for answer in answers:
        await repo.upsert(answer)
    first = await repo.get_canonical_answer("company_overview")

    # Second pass with freshly generated ids must not create duplicates.
    for answer in build_answers(datetime.now(UTC)):
        await repo.upsert(answer)
    second = await repo.get_canonical_answer("company_overview")

    all_answers = await repo.list_answers()
    assert len(all_answers) == len(answers)
    assert first.canonical_answer_id == second.canonical_answer_id
