# Privacy: retention & verified deletion

> **In one line:** Background jobs age out old data on a schedule, and a subject's access/deletion request is honored only after an operator verifies identity — recorded, audited, and executed by a worker, never inline on the request path.

**Status:** Live on staging (periods & notice pending Legal sign-off)  ·  **Introduced:** V1

## What it is
Two related privacy capabilities. **Retention** is a daily worker sweep (plus a database TTL) that hard-deletes data once it passes its class's retention period, so we don't hold conversations, requests, and feedback forever. **Verified deletion** (subject erasure / "right to be forgotten") lets a person ask us to delete or access their data through a public endpoint; nothing is deleted until an operator verifies their identity out of band, after which a background job erases their data across every store and writes an audit record. Both are job-driven — there are no ad-hoc deletes on the live request path (invariant #13).

## Why it exists
A public chatbot collects transcripts and contact details, so it needs a defensible, automatic answer to "how long do you keep this?" and "delete my data." The design leans on **[ADR-014](../03_Architecture_and_Decision_Records.md)** (MongoDB is the single source of truth; model calls are stateless with no provider-held conversation objects): because everything lives in one store, deletion is a single-store operation instead of a cross-system reconciliation problem. Verification-before-deletion exists so one person can never trigger erasure of someone else's data, and so an unauthenticated endpoint can't be used to probe what we hold.

## How it works
- **Retention sweep** (`run_retention_sweep`, daily): hard-deletes past-period rows across conversations, requests, feedback, and privacy-request records, in bounded batches so no run takes an unbounded delete lock; a backlog drains over successive days. Daily aggregates snapshot the counts first, so metrics survive the deletion.
- **Anonymous TTL:** abandoned conversations that never produced a request get an `expire_at` stamp and are auto-purged by a MongoDB TTL index. A conversation that converted to a request gets **no** TTL — it lives with its request to the long backstop, so no orphaned request.
- **Verified deletion:** public `POST /api/v1/privacy/requests` records the request as `pending` and returns an identical generic acknowledgement to everyone (never revealing whether we hold data; rate-limited per IP). An operator verifies identity out of band, which enqueues the `privacy_delete` job. That job redacts the subject's requests and conversations to non-PII tombstones and deletes their feedback, writes an audit entry **before** marking the request complete, and is idempotent (guarded updates make a replay a no-op).
- **Never dropped:** `run_privacy_reconcile` re-enqueues a verified-but-unfinished erasure whose job was lost (e.g. a crash between verify and enqueue), so a verified erasure always runs.

See [doc 04 §7–10](../04_API_and_Data_Contracts.md) for the contracts and PII rules.

## Key files
- `backend/app/domain/privacy/models.py` — the `PrivacyRequest` document; `verification_status` (pending/verified/rejected) gates execution, `status` (open/completed/failed) tracks fulfillment.
- `backend/app/domain/privacy/repository.py` — guarded lifecycle transitions (`mark_verified`, `mark_completed`), `list_verified_open` (reconcile source), and `delete_before` (retention of the request records themselves).
- `backend/app/api/public/privacy.py` — the unauthenticated intake endpoint with the fixed acknowledgement and per-IP rate limit.
- `backend/app/domain/jobs/tasks.py` — `run_retention_sweep`, `run_privacy_delete`, `run_privacy_reconcile`.
- `backend/app/domain/conversations/repository.py` — `delete_before` (retention), `redact_for_deletion` (tombstone), `mark_abandoned` (stamps the anonymous TTL), and the sparse `expire_at` TTL index.
- `backend/app/domain/requests/repository.py` / `feedback/repository.py` — the per-collection `redact_for_deletion` / `delete_for_conversations` / `delete_before` helpers the jobs call.
- `backend/app/api/admin/router.py` — the masked privacy-request list and the `verify` action (admin role, reason required, audited).
- `backend/app/core/config.py` — retention periods (see caveat below).
- `docs/PRIVACY_NOTICE.md` — the customer-facing notice (**DRAFT**).

## Interfaces
- **Public:** `POST /api/v1/privacy/requests` `{ type: "access"|"deletion", email, conversation_id? }` — unauthenticated, rate-limited, generic ack.
- **Admin:** `GET /api/v1/admin/privacy-requests` (email masked) · `POST /api/v1/admin/privacy-requests/{id}/verify` (admin role + reason, audited; enqueues `privacy_delete` for a deletion). Monitoring surfaces `privacy_by_status` and `privacy_failed` (alert if > 0).
- **Worker jobs:** `retention_sweep` (scheduled daily), `privacy_delete` (per verified deletion), `privacy_reconcile` (recovery). Plus the MongoDB TTL index on abandoned anonymous conversations.
- **Model tools:** none — the read-only model is never involved in retention or deletion.

## Status & limitations
- **Live on staging**, exercised end-to-end (intake → verify → erasure), including the failure paths (replay, lost-enqueue reconcile). No PII or message content in logs or the audit trail — jobs operate on counts, timestamps, and local IDs only (invariant #5); the erasure records `result_counts` (per-collection counts, no PII).
- **Retention periods are placeholders pending Legal/Privacy sign-off** (config defaults today: anonymous conversations 30d via TTL; conversations/requests/feedback 365d via sweep; privacy-request records 730d, kept longer as erasure proof). `docs/PRIVACY_NOTICE.md` is a **DRAFT** — the engineering description of behavior, not the final wording. The standing rule: if Legal changes a period, update `config.py` **and** the notice together so they never diverge.
- **Documented scope limit:** deletion covers every request bearing the verified email plus those requests' conversations. A `conversation_id` the subject names on the public endpoint is **not** auto-erased — it can't be proven theirs by email alone (honoring it blindly would let someone erase another person's transcript), so an unlinked anonymous transcript is left for an operator to handle via the audited admin path.
- **Access requests** are recorded and verified but fulfilled **manually** by an operator through the admin path — there is no automated access-export job yet.
- **Provider retention** (OpenAI): calls are stateless (`store=false`) with no provider-side conversation objects, so the provider holds no conversation as a business record; any transient operational logs it keeps fall under its own terms and are **documented, not deleted by us** — outside single-store deletion.

## Future & scaling
- **Legal confirmation** of the periods → update config + notice in lockstep; nothing else in the mechanism needs to change.
- **Automate access fulfillment** with an export builder so `type: "access"` produces the subject's data without a manual operator step.
- **Audited single-transcript erasure** as an admin action, closing the named-but-unlinked anonymous-conversation gap noted above.
- **Tune cadence/batch** (currently daily, bounded per run) if data volume grows enough that the backlog stops draining within a day.
- **V2 tenancy/regional controls** (`tenant_id`, `data_region` per [doc 04 §11](../04_API_and_Data_Contracts.md)) would make retention and deletion per-tenant and per-region rather than global.

## Related
- [Requests & external delivery](request-delivery.md) — creates the PII-bearing records that retention and erasure act on.
- [Admin audit trail](admin-roles-and-audit.md) — where every reveal, verify, and erasure is recorded.
- [Background worker & jobs](worker-and-jobs.md) — the scheduler that runs the sweep and erasure jobs.
- [doc 03 ADR-014](../03_Architecture_and_Decision_Records.md), [doc 04 §7–10](../04_API_and_Data_Contracts.md), `docs/PRIVACY_NOTICE.md` (DRAFT).
