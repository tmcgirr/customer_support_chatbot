from collections.abc import AsyncIterator
from typing import Any

import pytest
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import get_settings
from app.domain.jobs.repository import ensure_indexes as ensure_job_indexes

TEST_DB_NAME = "cadre_chatbot_test"
_COLLECTIONS = (
    "jobs",
    "conversations",
    "knowledge_sources",
    "requests",
    "feedback",
    "aggregates",
    "privacy_requests",
    "audit",
)

Database = AsyncIOMotorDatabase[dict[str, Any]]


@pytest.fixture
async def db() -> AsyncIterator[Database]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        get_settings().mongo_uri.get_secret_value(), tz_aware=True
    )
    database = client[TEST_DB_NAME]
    for name in _COLLECTIONS:
        await database[name].delete_many({})
    await ensure_job_indexes(database["jobs"])
    try:
        yield database
    finally:
        for name in _COLLECTIONS:
            await database[name].delete_many({})
        client.close()
