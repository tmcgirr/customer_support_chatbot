"""KnowledgeSourceRepository tests against real MongoDB (test DB).

Follows tests/domain/conftest.py: the ``knowledge_sources`` collection in
``cadre_chatbot_test`` is cleaned around each test.
"""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection

from app.domain.knowledge.repository import KnowledgeSourceRepository

Collection = AsyncIOMotorCollection[dict[str, Any]]


async def test_record_source_inserts_new(repo: KnowledgeSourceRepository) -> None:
    source = await repo.record_source(
        source_id="kbs_company_overview",
        openai_file_id="file_abc",
        vector_store_id="vs_1",
        title="Company Overview",
        category="company_overview",
        checksum="deadbeef",
        source_url="/knowledge/company-overview",
    )

    # The passed source_id becomes _id so message citations join back to it.
    assert source.id == "kbs_company_overview"
    assert source.openai_file_id == "file_abc"
    assert source.vector_store_id == "vs_1"
    assert source.title == "Company Overview"
    assert source.category == "company_overview"
    assert source.audience == "public"
    assert source.approved is True
    assert source.lifecycle == "active"
    assert source.indexing_status == "indexed"
    assert source.checksum == "deadbeef"
    assert source.created_at is not None
    assert source.updated_at is not None


async def test_record_source_upserts_by_file_id(repo: KnowledgeSourceRepository) -> None:
    first = await repo.record_source(
        source_id="kbs_same",
        openai_file_id="file_same",
        vector_store_id="vs_1",
        title="Old Title",
        category="company_overview",
    )
    second = await repo.record_source(
        source_id="kbs_ignored_on_update",
        openai_file_id="file_same",
        vector_store_id="vs_2",
        title="New Title",
        category="company_overview",
    )

    # Same underlying document: local id and created_at are fixed on first write.
    assert second.id == first.id
    assert second.created_at == first.created_at
    # Mutable metadata is updated in place.
    assert second.title == "New Title"
    assert second.vector_store_id == "vs_2"

    sources = await repo.list_sources()
    assert len(sources) == 1


async def test_list_sources_returns_all(repo: KnowledgeSourceRepository) -> None:
    assert await repo.list_sources() == []

    await repo.record_source(
        source_id="kbs_1", openai_file_id="file_1", vector_store_id="vs", title="One", category="a"
    )
    await repo.record_source(
        source_id="kbs_2", openai_file_id="file_2", vector_store_id="vs", title="Two", category="b"
    )

    sources = await repo.list_sources()
    assert len(sources) == 2
    assert {s.openai_file_id for s in sources} == {"file_1", "file_2"}
