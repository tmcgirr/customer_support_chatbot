# Admin knowledge management

> **In one line:** Admins upload, approve, remove, and replace the documents the bot can search — each action audited, and content only becomes searchable once explicitly approved.

**Status:** Live on staging (runs against a simulated store by default; a real OpenAI Vector Store when configured)  ·  **Introduced:** V1.5 (on the V1 knowledge-governance foundation)

## What it is
A screen in the admin SPA (plus its backing endpoints) that lets a Cadre operator manage the knowledge base the support bot retrieves from. Operators upload a document, review it, then **approve** it to make it searchable; they can **remove** a document to stop it being served or **replace** its file with a new version. MongoDB holds the governance record (title, category, owner, lifecycle, review date) while the actual file bytes live in an OpenAI Vector Store — the admin never sees provider IDs.

## Why it exists
The POC seeded knowledge through a one-off script (`scripts/upload_knowledge.py`). V1's public gate needs a governed, operable content lifecycle: someone accountable approves what the bot can say, changes are traceable, and bad content can be pulled fast. This capability turns that script-based sync into an audited admin workflow. It rests on two invariants: **canonical answers win / only approved content serves** (invariant #8) and **role-controlled, audited admin** (invariant #12). Retrieval itself is [ADR-007](../03_Architecture_and_Decision_Records.md) (OpenAI Vector Stores for RAG); the single public store is per [ADR-012](../03_Architecture_and_Decision_Records.md) (private/tenant stores stay V2+).

## How it works
- **Draft → approved gate.** Upload stores the file's bytes and records a governance row with `approved: false` — it is *not* attached to the Vector Store, so retrieval can't find it. **Approve** attaches the file to the store (stamping the local `kbs_` id + title/category as attributes) and only then flips `approved: true`. Serving is gated by *attachment*, not a flag alone, so an unapproved document is structurally unservable.
- **Indexing is asynchronous.** Attach may return `pending`; a `poll_indexing` worker job re-polls with backoff (budgeted ~15 attempts) until the file is `indexed` or `failed`, updating the row. The admin table shows the live state.
- **Remove / replace.** Remove *detaches* the file (retrieval stops) and marks the row `removed`. Replace uploads a new (unapproved) file, retires the old one as `replaced`, and detaches it — the new file needs its own approval.
- **Everything is audited.** Every upload/approve/remove/replace requires a typed **reason** and writes an append-only audit record *before* the store mutation, so a served-but-unaudited change can't exist. See [doc 04 §7–8](../04_API_and_Data_Contracts.md) for the `knowledge_sources` schema and indexes.

## Key files
- `backend/app/api/admin/router.py` — the `knowledge-sources` endpoints (list / upload / approve / remove / replace); shapes the browser-safe `KnowledgeSummary` that strips provider IDs.
- `backend/app/domain/knowledge/store.py` — the write boundary: `upload` / `attach` / `status` / `detach`. `OpenAIKnowledgeStore` (real) and `SimulatedKnowledgeStore` (default), chosen by `build_knowledge_store`. OpenAI IDs and errors are normalized here and never escape (invariant #4).
- `backend/app/domain/knowledge/repository.py` — governance metadata on the `knowledge_sources` collection (record, list, approve, set lifecycle, due-for-review).
- `backend/app/domain/knowledge/models.py` — the `KnowledgeSource` document (lifecycle, indexing status, provider IDs kept internal).
- `backend/app/domain/knowledge/search.py` — the read-side twin: retrieval queries the store directly, so attachment is the serving switch.
- `backend/app/domain/jobs/tasks.py` — `run_poll_indexing` and `run_knowledge_review_reminder`; scheduled in `backend/app/worker.py`.
- `frontend/src/admin/KnowledgeSources.tsx` — the Knowledge screen (upload form + per-row Approve / Replace / Remove).
- `frontend/src/admin/api.ts` — the admin client's knowledge methods.
- `backend/app/api/admin/auth.py` — `AdminRoleDep` (admin-only) vs `AdminDep` (admin or viewer read).

## Interfaces
- **Endpoints** (`/api/v1/admin/…`):
  - `GET /knowledge-sources` — list all sources (admin **or** viewer).
  - `POST /knowledge-sources` — upload (multipart: file + title + category + reason). Admin only.
  - `POST /knowledge-sources/{id}/approve` — attach + start indexing. Admin only.
  - `POST /knowledge-sources/{id}/remove` — detach + mark removed. Admin only.
  - `POST /knowledge-sources/{id}/replace` — upload a new file + retire the old. Admin only.
- **Worker jobs:** `poll_indexing` (per-source, retryable) and `knowledge_review_reminder` (daily; returns IDs of sources past `review_date`).
- **Admin screen:** the Knowledge tab — upload panel plus a table of Title / Category / Approved / Lifecycle / Indexing / Owner / Updated, with Approve / Replace / Remove actions for admins.

## Status & limitations
- **Live on staging.** The full upload → approve → remove/replace flow works end to end. By default the backend uses `SimulatedKnowledgeStore` (immediate `indexed`, no external calls); the real OpenAI-backed store activates only when `OPENAI_VECTOR_STORE_ID` is set — so whether a given environment hits a real Vector Store is a config choice, not visible in the UI.
- **Viewers are read-only.** A viewer can list sources; every mutation returns 403 (surfaced in the UI as "requires an admin role").
- **Provider isolation holds:** `openai_file_id` / `vector_store_id` are never sent to the browser (invariant #6); upload size is capped (~5 MB).
- **In progress — review reminders aren't surfaced yet.** The `knowledge_review_reminder` job computes which sources are past their `review_date`, and `KnowledgeSummary` carries `review_date`, but the admin table does not yet render a review-due column or badge (code comments tag this for a later wave). Treat "sources due for review" as plumbed, not shipped in the UI.

## Future & scaling
- **Surface review-due sources** in the Knowledge table (the job and data already exist) so stale content gets re-approved on cadence.
- **Bulk operations / staging→prod promotion.** Today content is managed per-source; V1's model promotes approved content from staging to production ([ADR-007](../03_Architecture_and_Decision_Records.md)), which this UI could drive directly rather than via scripts.
- **Richer retrieval controls** (metadata filters, score thresholds) are anticipated in ADR-007 and would layer onto the same category/attribute metadata this flow already stamps.
- **Format handling.** Uploads are treated as text/markdown docs; broader source types (PDF, HTML capture) would need ingestion/pre-processing before attach.
- Private/tenant-scoped stores and per-audience knowledge remain a **V2+** concern (ADR-012) — out of scope here.

## Related
- [Canonical answers](canonical-answers.md) — the other side of invariant #8: sensitive topics are served verbatim, never from retrieval.
- [Admin roles and audit](admin-roles-and-audit.md) — the role gate and append-only audit trail these actions write to.
- [Evaluation](evaluation.md) — the golden set that gates content/prompt changes before promotion.
- Architecture: [doc 03](../03_Architecture_and_Decision_Records.md) ADR-007 / ADR-012 / ADR-014. Contracts: [doc 04 §7–8](../04_API_and_Data_Contracts.md) (`knowledge_sources` schema + indexes) and the `search_knowledge` tool contract.
