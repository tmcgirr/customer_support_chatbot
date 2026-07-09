# Knowledge retrieval (OpenAI Vector Store)

> **In one line:** A managed, hybrid search over Cadre's approved public content that the chatbot can call as a read-only tool to ground factual answers about services, industries, approach, and partners.

**Status:** Live on staging  ·  **Introduced:** V1

## What it is

Knowledge retrieval is how the bot answers open-ended, factual questions ("what does Cadre do for healthcare?", "how do you approach an engagement?") with grounded content instead of model memory. Cadre's public knowledge lives as a small corpus of curated markdown documents that are uploaded into an **OpenAI Vector Store**; at answer time the model can call the `search_knowledge` tool, which queries that store and returns the most relevant passages plus a citable source for each. It is one of the model's three read-only tools — it reads content, it never writes or sends anything.

## Why it exists

The bot needs current, accurate, on-message facts about Cadre without letting a language model improvise them. Retrieval-augmented generation (RAG) solves this: ground every factual claim in approved source text. Per **ADR-007**, Cadre uses OpenAI's managed Vector Store with default hybrid retrieval rather than standing up its own embedding/index stack — the simplest option that meets V1 quality and control needs, revisited only for quality, cost, control, or isolation reasons. Retrieval deliberately covers only *general* topics; sensitive subjects (pricing, security, portal, case studies) never come from retrieval and instead use [canonical answers](canonical-answers.md) (ADR-008, invariant #8). Private/tenant knowledge stores stay a V2+ concern (**ADR-012**).

## How it works

- The model calls `search_knowledge(query, categories?, max_results?)`. The application — not the model — forces audience to `public`, so the only thing ever queried is the single public store.
- `KnowledgeSearch` calls the Vector Store search API, caps results at 5, optionally filters by a `category` attribute, and drops hits below a configurable relevance threshold (`retrieval_min_score`, default 0.0 = keep all).
- Each hit is normalized into a `SearchHit` carrying the local **`kbs_` source id**, title, content, score, and a public `display_url` — all read from attributes stamped onto the file at upload time, so a provider file id never reaches the caller. The orchestrator turns these into citations attached to the assistant message.
- **Degraded mode is safe:** on *any* provider error, or when no store is configured, search returns `SearchResult("unavailable", [])` and never raises (error code `RETRIEVAL_UNAVAILABLE`). The turn falls back to canonical answers and a retrieval-limitation message rather than failing. See [doc 04 §5](../04_API_and_Data_Contracts.md) and [doc 03 (ADR-007)](../03_Architecture_and_Decision_Records.md).

## Key files

- `backend/app/domain/knowledge/search.py` — the **read boundary**. Queries the store, caps/filters/normalizes hits, and guarantees no provider type, id, or exception escapes (invariants #4/#6). Owns the `RETRIEVAL_UNAVAILABLE` degraded path.
- `backend/app/domain/knowledge/store.py` — the **write boundary** (upload → attach → status → detach) for the admin knowledge UI. Serving is gated by *attachment* to the store: files are attached on approve, detached on remove/replace. Defaults to a functional in-process simulator when no store is configured.
- `backend/app/domain/knowledge/repository.py` — the `knowledge_sources` MongoDB collection: governance metadata (lifecycle, approval, indexing status, review dates), keyed so a citation's `source_id` joins back to its record.
- `backend/app/domain/knowledge/models.py` — the `KnowledgeSource` document; provider ids (`openai_file_id`, `vector_store_id`) are marked internal-only.
- `backend/app/agent/tools.py` — defines the `search_knowledge` read-only tool spec and executes it, shaping the JSON returned to the model and the out-of-band `Source` citations.
- `backend/scripts/upload_knowledge.py` — the manual sync: creates a fresh public store, uploads every `docs/knowledge/*.md`, stamps attributes, records governance rows, and prints the store id to set as `OPENAI_VECTOR_STORE_ID`.
- `docs/knowledge/*.md` — the corpus itself: roughly a dozen curated markdown docs (14 at time of writing) with `title`/`category`/`audience` front-matter (company overview, the four services, industries, engagement approach, outcomes, LLM partners, etc.).

## Interfaces

- **Model tool:** `search_knowledge` — read-only; in `{ query, categories?, max_results<=5 }`, out `{ results:[{source_id,title,content,score,display_url}], search_status }` ([doc 04 §5](../04_API_and_Data_Contracts.md)).
- **Admin API:** `GET /admin/knowledge-sources` lists sources (either role, not audited); the write actions — `POST /admin/knowledge-sources` (upload) and `POST /admin/knowledge-sources/{id}/{approve,remove,replace}` — are **`admin` role only and audited**. Provider ids are never exposed (invariant #6). Surfaced in the admin SPA's `KnowledgeSources` screen.
- **Worker jobs:** `run_poll_indexing` (records a just-uploaded file's indexing status) and `run_knowledge_review_reminder` (lists active sources past their `review_date` for a content owner to re-approve).
- **Script:** `uv run python scripts/upload_knowledge.py` (bulk corpus sync).

## Status & limitations

- The retrieval path, the `search_knowledge` tool, the `knowledge_sources` governance model, and the V1.5 admin knowledge-management screen are all **live**. Whether an environment queries a *real* OpenAI Vector Store or the built-in **simulator** depends solely on whether `OPENAI_VECTOR_STORE_ID` is set — the simulator lets the whole upload → approve → remove flow run in dev/tests with no OpenAI dependency.
- The corpus is small and hand-curated (roughly a dozen markdown files); retrieval quality is only as good as that content. "Retrieval quality acceptable" and "content gaps enumerated with owners" are explicit POC→V1 gate items ([doc 02 §8](../02_Release_Capability_Plan.md)).
- `retrieval_min_score` defaults to 0.0 (keep everything); it is meant to be tuned per environment against the store's real score distribution, and a mis-set threshold is observable via a content-free `knowledge.search.filtered` log marker.
- The bulk `upload_knowledge.py` script creates a **new** store each run and does not diff or delete prior content; ongoing edits are expected to move to the admin UI. Staging/production stores are separate and content is promoted, never edited directly in prod (invariant #14).

## Future & scaling

- **Metadata filters + thresholds at scale:** V1 already stamps `category` and supports `in`-filters and a score floor; as the corpus grows these become the main levers for precision. Doc 02 lists metadata filters and relevance thresholds plus controlled staging→production store promotion as the V1 direction.
- **Knowledge-gap ranking** ([doc 02 §2.6 later phases](../02_Release_Capability_Plan.md)): mine unmatched/low-score queries to prioritize which new documents to write — a natural feed into the admin review workflow already scaffolded by `KnowledgeGapItem`/review-reminder jobs.
- **Larger / richer corpus:** because serving is gated by attachment and every source carries lifecycle + review dates, the corpus can grow well beyond a dozen files without changing the retrieval boundary; the constraint is content authoring and review, not the mechanism.
- **Private / tenant stores (V2+):** ADR-012 keeps per-security-domain private Vector Stores out of V1. The audience-is-always-`public` invariant is the seam where that would later plug in — application-selected, never model-selected.

## Related

- [Canonical answers](canonical-answers.md) — the deterministic, always-wins path for sensitive topics; retrieval covers only general topics.
- [Content approval lifecycle](canonical-answers.md) — draft → approved gating that governs what may be served (invariant #8).
- [Chat orchestrator & read-only tools](chat-and-turn-loop.md) — how a turn calls the tool and attaches citations.
- [doc 03 — ADR-007, ADR-008, ADR-012, ADR-016](../03_Architecture_and_Decision_Records.md) · [doc 04 §5 (tools) & §7 (knowledge_sources)](../04_API_and_Data_Contracts.md) · [doc 02 §2.3 / §8](../02_Release_Capability_Plan.md)
