from collections.abc import AsyncIterator
from typing import Any

import pytest
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

from app.core.config import get_settings
from app.domain.conversations.repository import ConversationRepository, ensure_indexes

Collection = AsyncIOMotorCollection[dict[str, Any]]

# Isolated from the dev database; created/torn down around each test.
TEST_DB_NAME = "cadre_chatbot_test"


@pytest.fixture
async def conversations_collection() -> AsyncIterator[Collection]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        get_settings().mongo_uri.get_secret_value(), tz_aware=True
    )
    collection = client[TEST_DB_NAME]["conversations"]
    await collection.delete_many({})
    await ensure_indexes(collection)
    try:
        yield collection
    finally:
        await collection.delete_many({})
        client.close()


@pytest.fixture
async def repo(conversations_collection: Collection) -> ConversationRepository:
    return ConversationRepository(conversations_collection)
