from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from httpx import ASGITransport
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

from app.api.deps import (
    get_adapter,
    get_canonical_repository,
    get_conversation_repository,
    get_knowledge_search,
)
from app.core.config import get_settings
from app.domain.canonical.repository import (
    CanonicalAnswerRepository,
)
from app.domain.canonical.repository import (
    ensure_indexes as ensure_canonical,
)
from app.domain.conversations.repository import ConversationRepository, ensure_indexes
from app.main import app
from tests.fakes import FakeAdapter, FakeKnowledgeSearch

Collection = AsyncIOMotorCollection[dict[str, Any]]
TEST_DB_NAME = "cadre_chatbot_test"

DEFAULT_REPLY = "Cadre AI helps you move from AI confusion to AI confidence."


async def _fresh_collection(name: str) -> AsyncIterator[Collection]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        get_settings().mongo_uri.get_secret_value(), tz_aware=True
    )
    collection = client[TEST_DB_NAME][name]
    await collection.delete_many({})
    try:
        yield collection
    finally:
        await collection.delete_many({})
        client.close()


@pytest.fixture
async def collection() -> AsyncIterator[Collection]:
    async for coll in _fresh_collection("conversations"):
        await ensure_indexes(coll)
        yield coll


@pytest.fixture
async def canonical_collection() -> AsyncIterator[Collection]:
    async for coll in _fresh_collection("canonical_answers"):
        await ensure_canonical(coll)
        yield coll


@pytest.fixture
def fake_adapter() -> FakeAdapter:
    return FakeAdapter.replying(DEFAULT_REPLY)


@pytest.fixture
def fake_knowledge() -> FakeKnowledgeSearch:
    return FakeKnowledgeSearch()


@pytest.fixture
async def client(
    collection: Collection,
    canonical_collection: Collection,
    fake_adapter: FakeAdapter,
    fake_knowledge: FakeKnowledgeSearch,
) -> AsyncIterator[httpx.AsyncClient]:
    conversation_repo = ConversationRepository(collection)
    canonical_repo = CanonicalAnswerRepository(canonical_collection)
    app.dependency_overrides[get_conversation_repository] = lambda: conversation_repo
    app.dependency_overrides[get_canonical_repository] = lambda: canonical_repo
    app.dependency_overrides[get_adapter] = lambda: fake_adapter
    app.dependency_overrides[get_knowledge_search] = lambda: fake_knowledge
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac:
        yield ac
    app.dependency_overrides.clear()
