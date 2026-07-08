"""Manual knowledge sync: push docs/knowledge/*.md into an OpenAI Vector Store.

    uv run python scripts/upload_knowledge.py

Creates a fresh public Vector Store, uploads every approved markdown file, and
records governance metadata in MongoDB (contracts §7, ADR-007: script-based
upload at POC). Prints the new store id — copy it into ``backend/.env`` as
``OPENAI_VECTOR_STORE_ID`` so retrieval (`app/domain/knowledge/search.py`) can
find it.

Requires a real OPENAI_API_KEY and a reachable MongoDB (both via get_settings()).
If docs/knowledge/ is empty (still being written), the store is still created and
its id printed — the script never fails on missing content.
"""

import asyncio
import hashlib
import sys
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient
from openai import AsyncOpenAI

# Allow direct execution (`uv run python scripts/upload_knowledge.py`): Python only
# puts this file's directory on sys.path, so add the backend root for `app`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import ids  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.domain.knowledge.repository import (  # noqa: E402
    KnowledgeSourceRepository,
    ensure_indexes,
)

STORE_NAME = "cadre-public-knowledge"
# scripts/ -> backend/ -> repo root; knowledge lives at <root>/docs/knowledge.
KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "docs" / "knowledge"


def _parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Split a leading ``---`` YAML-ish front-matter block into (fields, body).

    Only flat ``key: value`` lines are supported — enough for the knowledge docs
    and free of a YAML dependency. Files without front-matter return ({}, text).
    """
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, text
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return fields, body


def _load_files() -> list[tuple[str, str, bytes]]:
    """Read every knowledge markdown file up front (sync I/O, off the async path).

    Returns ``(filename, stem, raw_bytes)`` tuples; empty if the directory is
    missing or has no markdown (another agent may still be writing it).
    """
    if not KNOWLEDGE_DIR.is_dir():
        return []
    return [(p.name, p.stem, p.read_bytes()) for p in sorted(KNOWLEDGE_DIR.glob("*.md"))]


async def _upload_one(
    client: AsyncOpenAI,
    repo: KnowledgeSourceRepository,
    vector_store_id: str,
    filename: str,
    stem: str,
    raw: bytes,
) -> None:
    fields, _ = _parse_front_matter(raw.decode("utf-8", errors="replace"))
    title = fields.get("title") or stem.replace("-", " ").title()
    category = fields.get("category") or "general"
    # Local id generated up front so it can be stamped onto the file as an
    # attribute; retrieval reads it back as SearchHit.source_id (never the file id).
    source_id = ids.knowledge_source_id()
    display_url = f"/knowledge/{stem}"
    checksum = hashlib.sha256(raw).hexdigest()

    vector_file = await client.vector_stores.files.upload_and_poll(
        vector_store_id=vector_store_id,
        file=(filename, raw),
        attributes={
            "source_id": source_id,
            "title": title[:512],
            "category": category[:512],
            "display_url": display_url[:512],
        },
    )
    status = getattr(vector_file, "status", "")
    indexing_status = "indexed" if status == "completed" else "failed"

    source = await repo.record_source(
        source_id=source_id,
        openai_file_id=vector_file.id,
        vector_store_id=vector_store_id,
        title=title,
        category=category,
        indexing_status=indexing_status,
        source_url=display_url,
        checksum=checksum,
    )
    print(f"  uploaded {filename:<44} -> {source.id}  [{indexing_status}]")


async def main() -> None:
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
    mongo: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        settings.mongo_uri.get_secret_value(), tz_aware=True
    )
    collection = mongo[settings.mongo_db_name]["knowledge_sources"]
    await ensure_indexes(collection)
    repo = KnowledgeSourceRepository(collection)

    try:
        store = await client.vector_stores.create(name=STORE_NAME)
        print(f"Created vector store '{STORE_NAME}': {store.id}")

        files = _load_files()
        if not files:
            print(f"No markdown files under {KNOWLEDGE_DIR} — created an empty store.")
        else:
            print(f"Uploading {len(files)} file(s) from {KNOWLEDGE_DIR} ...")
            for filename, stem, raw in files:
                await _upload_one(client, repo, store.id, filename, stem, raw)

        print("\nDone. Set this in backend/.env so retrieval can find the store:")
        print(f"\n    OPENAI_VECTOR_STORE_ID={store.id}\n")
    finally:
        await client.close()
        mongo.close()


if __name__ == "__main__":
    asyncio.run(main())
