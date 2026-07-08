from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core import ids
from app.core.config import get_settings
from app.domain.jobs.repository import ensure_indexes as ensure_job_indexes
from app.domain.requests.models import Contact, RequestRecord, RequestType
from app.domain.requests.repository import RequestRepository
from app.domain.requests.repository import ensure_indexes as ensure_request_indexes

TEST_DB_NAME = "cadre_chatbot_test"
_COLLECTIONS = ("requests", "conversations", "jobs")

Database = AsyncIOMotorDatabase[dict[str, Any]]


@pytest.fixture
async def db() -> AsyncIterator[Database]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        get_settings().mongo_uri.get_secret_value(), tz_aware=True
    )
    database = client[TEST_DB_NAME]
    for name in _COLLECTIONS:
        await database[name].delete_many({})
    await ensure_request_indexes(database["requests"])
    await ensure_job_indexes(database["jobs"])
    try:
        yield database
    finally:
        for name in _COLLECTIONS:
            await database[name].delete_many({})
        client.close()


async def make_request(
    repo: RequestRepository,
    *,
    request_type: RequestType = "strategy_call",
    status: str = "received",
    reference: str = "REF-TEST",
) -> RequestRecord:
    """Insert a persisted request directly (bypassing submit) for delivery tests."""
    record = RequestRecord(
        id=ids.request_id(),
        type=request_type,
        conversation_id="cnv_test",
        idempotency_key=ids.prefixed_id("key"),
        reference=reference,
        contact=Contact(email="a@b.com"),
        consent_version="consent-2026-07",
        status=status,  # type: ignore[arg-type]
        created_at=datetime.now(UTC),
    )
    await repo._collection.insert_one(record.model_dump(by_alias=True))  # noqa: SLF001 (test setup)
    return record
