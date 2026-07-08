"""KnowledgeSearch tests: synthetic Vector Store responses -> normalized results.

The real OpenAI SDK is never called. A fake AsyncOpenAI-shaped client returns
hand-built search pages (or raises) through ``vector_stores.search``.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from openai import OpenAIError

from app.domain.knowledge.search import KnowledgeSearch, SearchHit, SearchResult


def _hit(**kwargs: Any) -> SimpleNamespace:
    """A fake VectorStoreSearchResponse item."""
    defaults: dict[str, Any] = {
        "file_id": "file_x",
        "filename": "doc.md",
        "score": 0.5,
        "attributes": {},
        "content": [],
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _content(*texts: str) -> list[SimpleNamespace]:
    return [SimpleNamespace(type="text", text=t) for t in texts]


class _FakeVectorStores:
    def __init__(self, page: Any, raise_exc: Exception | None) -> None:
        self._page = page
        self._raise = raise_exc
        self.last_kwargs: dict[str, Any] | None = None
        self.call_count = 0

    async def search(self, **kwargs: Any) -> Any:
        self.call_count += 1
        self.last_kwargs = kwargs
        if self._raise is not None:
            raise self._raise
        return self._page


class _FakeClient:
    def __init__(
        self, *, hits: list[Any] | None = None, raise_exc: Exception | None = None
    ) -> None:
        page = SimpleNamespace(data=list(hits) if hits is not None else [])
        self.vector_stores = _FakeVectorStores(page, raise_exc)

    async def close(self) -> None:
        pass


def _search(client: _FakeClient, *, vector_store_id: str = "vs_test") -> KnowledgeSearch:
    return KnowledgeSearch(client=client, vector_store_id=vector_store_id)  # type: ignore[arg-type]


async def test_normalizes_hits_into_search_hits() -> None:
    client = _FakeClient(
        hits=[
            _hit(
                filename="company-overview.md",
                score=0.91,
                attributes={
                    "source_id": "kbs_01ABC",
                    "title": "Company Overview",
                    "display_url": "/knowledge/company-overview",
                    "category": "company_overview",
                },
                content=_content("Cadre AI is a consultancy.", "It helps businesses."),
            )
        ]
    )
    result = await _search(client).search("what does cadre do")

    assert isinstance(result, SearchResult)
    assert result.status == "ok"
    assert len(result.results) == 1
    hit = result.results[0]
    assert isinstance(hit, SearchHit)
    assert hit.source_id == "kbs_01ABC"
    assert hit.title == "Company Overview"
    assert hit.content == "Cadre AI is a consultancy.\nIt helps businesses."
    assert hit.score == pytest.approx(0.91)
    assert hit.display_url == "/knowledge/company-overview"


async def test_missing_attributes_degrade_to_filename_and_empty() -> None:
    # A hit without attributes must still normalize without raising.
    client = _FakeClient(hits=[_hit(filename="orphan.md", attributes=None, content=_content("hi"))])
    result = await _search(client).search("q")

    assert result.status == "ok"
    hit = result.results[0]
    assert hit.source_id == ""
    assert hit.title == "orphan.md"
    assert hit.display_url == ""
    assert hit.content == "hi"


async def test_no_hits_returns_empty_status() -> None:
    result = await _search(_FakeClient(hits=[])).search("nothing matches")
    assert result.status == "empty"
    assert result.results == []


async def test_provider_error_returns_unavailable_without_raising() -> None:
    client = _FakeClient(raise_exc=OpenAIError("boom"))
    result = await _search(client).search("q")
    assert result.status == "unavailable"
    assert result.results == []


async def test_any_exception_returns_unavailable() -> None:
    # ANY provider error, not just OpenAIError, is caught at this boundary.
    client = _FakeClient(raise_exc=RuntimeError("unexpected"))
    result = await _search(client).search("q")
    assert result.status == "unavailable"
    assert result.results == []


async def test_empty_vector_store_id_returns_unavailable_and_skips_call() -> None:
    client = _FakeClient(hits=[_hit()])
    result = await _search(client, vector_store_id="").search("q")
    assert result.status == "unavailable"
    assert result.results == []
    # The provider is never queried when no store is configured.
    assert client.vector_stores.call_count == 0


async def test_max_results_capped_at_five() -> None:
    client = _FakeClient(hits=[])
    await _search(client).search("q", max_results=50)
    assert client.vector_stores.last_kwargs is not None
    assert client.vector_stores.last_kwargs["max_num_results"] == 5


async def test_max_results_passed_through_when_below_cap() -> None:
    client = _FakeClient(hits=[])
    await _search(client).search("q", max_results=3)
    assert client.vector_stores.last_kwargs is not None
    assert client.vector_stores.last_kwargs["max_num_results"] == 3


async def test_returned_hits_truncated_to_cap() -> None:
    # Even if the provider over-returns, we never surface more than the cap.
    client = _FakeClient(hits=[_hit(attributes={"source_id": f"kbs_{i}"}) for i in range(9)])
    result = await _search(client).search("q", max_results=2)
    assert result.status == "ok"
    assert len(result.results) == 2


async def test_categories_become_an_in_filter() -> None:
    client = _FakeClient(hits=[])
    await _search(client).search("q", categories=["service_overview", "company_overview"])
    assert client.vector_stores.last_kwargs is not None
    assert client.vector_stores.last_kwargs["filters"] == {
        "type": "in",
        "key": "category",
        "value": ["service_overview", "company_overview"],
    }


async def test_no_categories_sends_no_filter() -> None:
    client = _FakeClient(hits=[])
    await _search(client).search("q")
    assert client.vector_stores.last_kwargs is not None
    assert "filters" not in client.vector_stores.last_kwargs
