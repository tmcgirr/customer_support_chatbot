"""Knowledge retrieval boundary (contracts §5 ``search_knowledge``, ADR-007).

The OpenAI Vector Store search API is called ONLY here. This module is to
retrieval what ``app/agent/adapter.py`` is to chat: no provider type escapes it,
and it never raises. Audience is forced to ``public`` structurally — the only
store this ever queries is the single public one.

Degraded mode (ADR §6, error code ``RETRIEVAL_UNAVAILABLE``): on *any* provider
failure, or when no store is configured, ``search`` logs a content-free marker
and returns ``SearchResult("unavailable", [])``. Callers fall back to canonical
answers and the retrieval-limitation message; they never see an exception.
"""

from dataclasses import dataclass
from typing import Any, Literal

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Contracts §5 caps search_knowledge at 5 results regardless of what is requested.
MAX_RESULTS = 5

SearchStatus = Literal["ok", "empty", "unavailable"]


@dataclass(frozen=True)
class SearchHit:
    source_id: str
    title: str
    content: str
    score: float
    display_url: str


@dataclass(frozen=True)
class SearchResult:
    status: str
    results: list[SearchHit]


def _log_unavailable(reason: str) -> None:
    """Structured, content-free marker for the RETRIEVAL_UNAVAILABLE path.

    No query, store id, or provider payload — a reason marker only (contracts §10,
    CLAUDE.md invariant #5). ``query`` is a forbidden log key by construction.
    """
    logger.warning("knowledge.search.unavailable", extra={"context": {"reason": reason}})


def _hit_content(item: Any) -> str:
    chunks = getattr(item, "content", None) or []
    texts = [getattr(chunk, "text", "") for chunk in chunks]
    return "\n".join(text for text in texts if text)


def _to_hit(item: Any) -> SearchHit:
    """Normalize one provider search result into a SearchHit.

    ``source_id``/``title``/``display_url`` are read from file attributes set at
    upload time (see ``scripts/upload_knowledge.py``) so the public ``kbs_`` id —
    not the provider file id — flows to callers. Reads are defensive: a hit
    missing attributes degrades to empty/filename rather than raising.
    """
    attributes = getattr(item, "attributes", None) or {}
    return SearchHit(
        source_id=str(attributes.get("source_id") or ""),
        title=str(attributes.get("title") or getattr(item, "filename", "") or ""),
        content=_hit_content(item),
        score=float(getattr(item, "score", 0.0) or 0.0),
        display_url=str(attributes.get("display_url") or ""),
    )


class KnowledgeSearch:
    def __init__(
        self, client: AsyncOpenAI | None = None, vector_store_id: str | None = None
    ) -> None:
        self._client = client or AsyncOpenAI(
            api_key=get_settings().openai_api_key.get_secret_value()
        )
        self._vector_store_id: str = (
            vector_store_id
            if vector_store_id is not None
            else get_settings().openai_vector_store_id
        )

    async def search(
        self, query: str, *, categories: list[str] | None = None, max_results: int = 5
    ) -> SearchResult:
        """Query the public knowledge store; return a normalized, safe result.

        Never raises: any provider error or a missing store id yields
        ``SearchResult("unavailable", [])``. No hits yields ``"empty"``.
        ``max_results`` is clamped to [1, 5] (contracts §5).
        """
        capped = max(1, min(max_results, MAX_RESULTS))

        if not self._vector_store_id:
            _log_unavailable("no_store_configured")
            return SearchResult("unavailable", [])

        request: dict[str, Any] = {
            "vector_store_id": self._vector_store_id,
            "query": query,
            "max_num_results": capped,
        }
        if categories:
            # Filter on the category attribute stamped onto each file at upload.
            request["filters"] = {"type": "in", "key": "category", "value": list(categories)}

        try:
            page: Any = await self._client.vector_stores.search(**request)
            hits = [_to_hit(item) for item in (page.data or [])]
        # Broad by design: this is the RETRIEVAL_UNAVAILABLE boundary, so no
        # provider exception (or anything else) may propagate past it. Cancellation
        # inherits BaseException, so it is not swallowed here.
        except Exception:
            _log_unavailable("provider_error")
            return SearchResult("unavailable", [])

        hits = hits[:capped]
        if not hits:
            return SearchResult("empty", [])
        return SearchResult("ok", hits)

    async def aclose(self) -> None:
        await self._client.close()
