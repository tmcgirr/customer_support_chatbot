"""LlmUsageRepository — $inc daily rollup upserts keyed by (date, provider, model, category)."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

from app.core.config import get_settings
from app.domain.usage.repository import LlmUsageRepository

Collection = AsyncIOMotorCollection[dict[str, Any]]
TEST_DB_NAME = "cadre_chatbot_test"


@pytest.fixture
async def llm_usage_collection() -> AsyncIterator[Collection]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        get_settings().mongo_uri.get_secret_value(), tz_aware=True
    )
    collection = client[TEST_DB_NAME]["llm_usage"]
    await collection.delete_many({})
    try:
        yield collection
    finally:
        await collection.delete_many({})
        client.close()


async def test_record_accumulates_into_one_row(llm_usage_collection: Collection) -> None:
    repo = LlmUsageRepository(llm_usage_collection)
    await repo.record("claude-haiku-4-5", "summary", 100, 50)
    await repo.record("claude-haiku-4-5", "summary", 10, 5)
    rows = await repo.rows_since("2000-01-01")
    assert len(rows) == 1
    row = rows[0]
    assert row["input_tokens"] == 110
    assert row["output_tokens"] == 55
    assert row["requests"] == 2
    assert row["provider"] == "anthropic"  # inferred from the model id
    assert row["category"] == "summary"


async def test_record_keeps_dimensions_separate(llm_usage_collection: Collection) -> None:
    repo = LlmUsageRepository(llm_usage_collection)
    await repo.record("claude-haiku-4-5", "summary", 1, 1)
    await repo.record("gpt-5.4-mini", "labeling", 1, 1)
    await repo.record("anthropic/claude-haiku-4.5", "insights", 1, 1)  # OpenRouter
    rows = await repo.rows_since("2000-01-01")
    assert len(rows) == 3
    assert {r["provider"] for r in rows} == {"anthropic", "openai", "openrouter"}


async def test_rows_since_filters_by_date(llm_usage_collection: Collection) -> None:
    # A row dated in the past must be excluded by a later `since`.
    await llm_usage_collection.insert_one(
        {
            "_id": "1999-01-01:openai:gpt-5.4-mini:labeling",
            "date": "1999-01-01",
            "provider": "openai",
            "model": "gpt-5.4-mini",
            "category": "labeling",
            "input_tokens": 5,
            "output_tokens": 5,
            "requests": 1,
        }
    )
    repo = LlmUsageRepository(llm_usage_collection)
    await repo.record("claude-haiku-4-5", "summary", 1, 1)  # today
    assert len(await repo.rows_since("1999-01-01")) == 2
    assert len(await repo.rows_since("2500-01-01")) == 0
