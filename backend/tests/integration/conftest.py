from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from httpx import ASGITransport
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

from app.api.deps import get_adapter, get_conversation_repository
from app.core.config import get_settings
from app.domain.conversations.repository import ConversationRepository, ensure_indexes
from app.main import app
from tests.fakes import FakeAdapter

Collection = AsyncIOMotorCollection[dict[str, Any]]
TEST_DB_NAME = "cadre_chatbot_test"

DEFAULT_REPLY = "Cadre AI helps you move from AI confusion to AI confidence."


@pytest.fixture
async def collection() -> AsyncIterator[Collection]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        get_settings().mongo_uri.get_secret_value(), tz_aware=True
    )
    coll = client[TEST_DB_NAME]["conversations"]
    await coll.delete_many({})
    await ensure_indexes(coll)
    try:
        yield coll
    finally:
        await coll.delete_many({})
        client.close()


@pytest.fixture
def fake_adapter() -> FakeAdapter:
    return FakeAdapter.replying(DEFAULT_REPLY)


@pytest.fixture
async def client(
    collection: Collection, fake_adapter: FakeAdapter
) -> AsyncIterator[httpx.AsyncClient]:
    repo = ConversationRepository(collection)
    app.dependency_overrides[get_conversation_repository] = lambda: repo
    app.dependency_overrides[get_adapter] = lambda: fake_adapter
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac:
        yield ac
    app.dependency_overrides.clear()
