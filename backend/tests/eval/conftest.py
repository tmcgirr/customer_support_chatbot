from collections.abc import AsyncIterator
from typing import Any

import pytest
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import get_settings

TEST_DB_NAME = "cadre_chatbot_test"
Database = AsyncIOMotorDatabase[dict[str, Any]]
_COLLECTIONS = ("conversations", "canonical_answers")


@pytest.fixture
async def db() -> AsyncIterator[Database]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        get_settings().mongo_uri.get_secret_value(), tz_aware=True
    )
    database = client[TEST_DB_NAME]
    for name in _COLLECTIONS:
        await database[name].delete_many({})
    try:
        yield database
    finally:
        for name in _COLLECTIONS:
            await database[name].delete_many({})
        client.close()
