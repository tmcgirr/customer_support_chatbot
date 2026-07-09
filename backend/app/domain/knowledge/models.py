"""Knowledge source document model (contracts §7).

Governance metadata for every approved, searchable file. MongoDB owns this
record; the actual file bytes live in the OpenAI Vector Store. The provider IDs
(``openai_file_id``, ``vector_store_id``) are internal only — public APIs expose
the local ``kbs_`` id (contracts §1, CLAUDE.md invariant #6).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

KnowledgeAudience = Literal["public"]
KnowledgeLifecycle = Literal["active", "replaced", "removed"]
IndexingStatus = Literal["pending", "indexed", "failed"]


class KnowledgeSource(BaseModel):
    # populate_by_name lets us construct with `id=` while Mongo stores `_id`.
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")
    title: str
    category: str
    # Audience is always public at POC (ADR-012 keeps private stores a V2+ concern);
    # the single public store is the only thing retrieval ever queries.
    audience: KnowledgeAudience = "public"
    language: str = "en"
    approved: bool = False
    lifecycle: KnowledgeLifecycle = "active"
    indexing_status: IndexingStatus = "pending"
    # Provider IDs — internal only, never exposed to the browser.
    openai_file_id: str | None = None
    vector_store_id: str | None = None
    source_url: str | None = None
    version: str = "1"
    owner: str = "cadre"
    effective_date: datetime | None = None
    review_date: datetime | None = None
    checksum: str | None = None
    # A local copy of the document's decoded text, for the admin viewer. None for a
    # binary/non-UTF-8 upload or a legacy record from before previews were stored.
    # NEVER included in list responses / KnowledgeSummary; served only via the
    # content endpoint. Cadre's own content, not PII.
    content_text: str | None = None
    created_at: datetime
    updated_at: datetime
