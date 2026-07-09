"""Knowledge-store WRITE boundary (upload / attach / index-status / detach).

The retrieval read path lives in ``search.py``; this is its write-side twin for
the admin knowledge-management UI. Same rule (invariant #4/#6): the OpenAI client,
its file ids, and its errors NEVER leave this module — callers get a normalized
``IndexingStatus`` / file id or a ``KnowledgeStoreError``.

Serving is gated by ATTACHMENT to the Vector Store, which retrieval queries
directly: `upload` stores the file's bytes but does NOT make it searchable;
`attach` (on admin approve) adds it to the store so it can be retrieved; `detach`
(on remove/replace) takes it back out. So an unapproved file is never served.

Default is a functional SIMULATOR (no OpenAI, immediate "indexed") so the whole
pipeline runs in dev/tests without a store; when a Vector Store IS configured the
real OpenAI-backed store is used. Chosen by ``build_knowledge_store``.
"""

from typing import Any, Protocol, cast

from openai import AsyncOpenAI

from app.core import ids
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain.knowledge.models import IndexingStatus

logger = get_logger("app.knowledge.store")


class KnowledgeStoreError(Exception):
    """Normalized store failure. ``retryable`` distinguishes a transient fault
    (retry) from a permanent one (surface to the admin)."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


def _map_status(raw: str) -> IndexingStatus:
    if raw == "completed":
        return "indexed"
    if raw in ("failed", "cancelled"):
        return "failed"
    return "pending"  # in_progress / anything else


class KnowledgeStore(Protocol):
    channel: str

    async def upload(self, *, filename: str, content: bytes) -> str:
        """Store the file's bytes; return a provider file id. NOT yet searchable."""
        ...

    async def attach(self, file_id: str, *, attributes: dict[str, str]) -> IndexingStatus:
        """Add the file to the Vector Store so retrieval can find it (on approve)."""
        ...

    async def status(self, file_id: str) -> IndexingStatus: ...

    async def detach(self, file_id: str) -> None:
        """Remove the file from the Vector Store (on remove/replace) so it stops serving."""
        ...


class SimulatedKnowledgeStore:
    """Default store: no external calls, files report immediately indexed. Lets the whole
    upload → approve → remove flow run without an OpenAI Vector Store (dev/tests)."""

    channel = "simulated"

    async def upload(self, *, filename: str, content: bytes) -> str:
        logger.info("knowledge.store.simulated_upload", extra={"context": {"bytes": len(content)}})
        return f"simfile_{ids.prefixed_id('kf')}"

    async def attach(self, file_id: str, *, attributes: dict[str, str]) -> IndexingStatus:
        return "indexed"

    async def status(self, file_id: str) -> IndexingStatus:
        return "indexed"

    async def detach(self, file_id: str) -> None:
        return None


class OpenAIKnowledgeStore:
    """Real store: uploads bytes to OpenAI Files, then (on approve) attaches to the Vector
    Store with the local ``source_id`` (+ title/category/display_url) as attributes so
    retrieval reads them back. Provider errors are caught and normalized here."""

    channel = "openai"

    def __init__(self, client: AsyncOpenAI, vector_store_id: str) -> None:
        self._client = client
        self._vs = vector_store_id

    async def upload(self, *, filename: str, content: bytes) -> str:
        try:
            uploaded: Any = await self._client.files.create(
                file=(filename, content), purpose="assistants"
            )
        except Exception:
            raise KnowledgeStoreError("upload_failed", retryable=True) from None
        return str(uploaded.id)

    async def attach(self, file_id: str, *, attributes: dict[str, str]) -> IndexingStatus:
        try:
            vector_file: Any = await self._client.vector_stores.files.create(
                vector_store_id=self._vs,
                file_id=file_id,
                attributes=cast("dict[str, str | float | bool]", attributes),
            )
        except Exception:
            raise KnowledgeStoreError("attach_failed", retryable=True) from None
        return _map_status(str(getattr(vector_file, "status", "")))

    async def status(self, file_id: str) -> IndexingStatus:
        try:
            vector_file: Any = await self._client.vector_stores.files.retrieve(
                file_id, vector_store_id=self._vs
            )
        except Exception:
            raise KnowledgeStoreError("status_failed", retryable=True) from None
        return _map_status(str(getattr(vector_file, "status", "")))

    async def detach(self, file_id: str) -> None:
        try:
            await self._client.vector_stores.files.delete(file_id, vector_store_id=self._vs)
        except Exception:
            raise KnowledgeStoreError("detach_failed", retryable=True) from None

    async def aclose(self) -> None:
        await self._client.close()


def build_knowledge_store(settings: Settings) -> KnowledgeStore:
    """Real OpenAI store when a Vector Store is configured; the simulated mock otherwise.
    Switching a real store on is a config change (set OPENAI_VECTOR_STORE_ID)."""
    if settings.openai_vector_store_id.strip():
        client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
        return OpenAIKnowledgeStore(client, settings.openai_vector_store_id)
    logger.warning("knowledge.store.no_vector_store", extra={"context": {}})
    return SimulatedKnowledgeStore()
