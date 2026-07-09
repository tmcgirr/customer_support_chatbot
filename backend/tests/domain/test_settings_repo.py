"""SettingsRepository — the runtime model-provider toggle (single upsert doc)."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

from app.core.config import get_settings
from app.domain.settings.repository import SettingsRepository

Collection = AsyncIOMotorCollection[dict[str, Any]]
TEST_DB_NAME = "cadre_chatbot_test"


@pytest.fixture
async def app_settings_collection() -> AsyncIterator[Collection]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        get_settings().mongo_uri.get_secret_value(), tz_aware=True
    )
    collection = client[TEST_DB_NAME]["app_settings"]
    await collection.delete_many({})
    try:
        yield collection
    finally:
        await collection.delete_many({})
        client.close()


async def test_defaults_to_config_provider_when_unset(app_settings_collection: Collection) -> None:
    repo = SettingsRepository(app_settings_collection)
    assert await repo.get_active_provider() == get_settings().model_provider


async def test_set_then_get_round_trips(app_settings_collection: Collection) -> None:
    repo = SettingsRepository(app_settings_collection)
    setting = await repo.set_active_provider("anthropic", updated_by="admin")
    assert setting.active_provider == "anthropic"
    assert setting.updated_by == "admin"
    assert await repo.get_active_provider() == "anthropic"


async def test_set_is_single_doc_upsert(app_settings_collection: Collection) -> None:
    repo = SettingsRepository(app_settings_collection)
    await repo.set_active_provider("anthropic", updated_by="a")
    await repo.set_active_provider("openai", updated_by="b")
    assert await repo.get_active_provider() == "openai"
    # A switch replaces the one doc; it never accumulates history rows.
    assert await app_settings_collection.count_documents({}) == 1
