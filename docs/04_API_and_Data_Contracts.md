# Cadre AI Customer Support Chatbot
## API and Data Contracts Specification

**Status:** Current implementation contract (Revision 3)
**Primary scope:** POC and V1

---

# 1. Principles

- Local ULID/UUIDv7 IDs in all public APIs; provider IDs (file/store) internal only.
- Version APIs under `/api/v1`; UTC timestamps everywhere.
- Idempotency keys required for every write.
- The model is read-only; the browser performs writes via typed endpoints.
- Public and admin responses are separate models; admin masks PII by default.

ID prefixes: `cnv_` conversation · `msg_` message · `req_` request · `kbs_` knowledge source · `can_` canonical answer · `fbk_` feedback · `pvr_` privacy request · `job_` job · `evc_` eval case.

---

# 2. Session Model

`POST /api/v1/conversations` returns an **HMAC-signed stateless token**:

```
payload = { cid: "cnv_01J...", iat, exp }   # exp default: 24h
token   = base64(payload) + "." + HMAC_SHA256(secret, payload)
```

The browser sends it as a Bearer header. The server validates signature + expiry and checks `cid` against the path. No session collection exists. Rotation: secrets are versioned; tokens carry a key ID.

The browser never receives provider IDs, database internals, or credentials.

---

# 3. Public APIs (5 endpoints)

## 3.1 Create conversation

`POST /api/v1/conversations`

```json
// request
{ "entry_page": "/services/ai-agents", "locale": "en-US", "consent_version": "privacy-2026-07" }
// response
{
  "conversation_id": "cnv_01JABC",
  "session_token": "…",
  "welcome": {
    "text": "Hi, I'm Cadre AI's virtual assistant. …",
    "suggested_actions": [
      {"id": "company_overview", "label": "What does Cadre AI do?"},
      {"id": "industry_fit",     "label": "Do you work with my industry?"},
      {"id": "strategy_call",    "label": "Book a strategy call"},
      {"id": "portal_access",    "label": "Access the client portal"}
    ]
  }
}
```

Per-IP creation cap enforced here (POC: app-level counter with TTL; V1: edge).

## 3.2 Send message (SSE)

`POST /api/v1/conversations/{conversation_id}/messages`
Headers: `Authorization: Bearer <token>`, `Idempotency-Key` (= client_message_id), `Accept: text/event-stream`.

```json
{ "content": "Do you work with construction companies?", "client_message_id": "cmid_9f3…" }
```

Events: `message.accepted` → `response.started` → `response.delta`* → [`response.citation`*] → [`action.offered`*] → `response.completed` | `response.failed` | `limit.reached`.

`response.completed`:

```json
{ "assistant_message_id": "msg_01JAS",
  "suggested_actions": [{"id": "strategy_call", "label": "Talk to a strategist"}] }
```

Duplicate `client_message_id` replays the stored result. Concurrent send returns 409 `CONVERSATION_BUSY`.

## 3.3 Get transcript

`GET /api/v1/conversations/{conversation_id}/messages` — the owner's visible transcript (id, role, content, status, suggested_actions, created_at). Used for reconnect/refresh.

## 3.4 Submit request (all three workflow types)

`POST /api/v1/requests`
Headers: Bearer token, `Idempotency-Key`.

```json
{
  "type": "strategy_call",              // strategy_call | portal_support | human_escalation
  "conversation_id": "cnv_01JABC",
  "contact": { "name": "Ada Smith", "email": "ada@acme.com", "company": "Acme" },
  "fields": {
    // strategy_call:    { "reason": "...", "industry"?: "...", "region"?: "..." }
    // portal_support:   { "issue_category": "forgot_password|no_access|error|other",
    //                     "description": "...", "error_message"?: "...", "steps_attempted"?: "..." }
    // human_escalation: { "category": "...", "original_question": "...", "context_summary": "..." }
  },
  "consent_version": "consent-2026-07",
  "confirmed": true
}
```

```json
// response
{ "request_id": "req_01JXYZ", "status": "received", "reference": "REQ-8F3K" }
```

Validation: email format, per-type required fields, `confirmed: true`, consent version present. Server-side per-type schema; drafts are never persisted server-side. `human_escalation` accepts an empty contact when the user declines to provide one.

## 3.5 Feedback

`POST /api/v1/messages/{message_id}/feedback` — `{ "rating": "helpful|not_helpful", "reason"?: "incorrect|unclear|did_not_answer|need_person|other", "comment"?: "…" }` with Bearer token; message must belong to the session's conversation.

Also: `POST /api/v1/privacy/requests` (V1) — `{ "type": "access|deletion", "email": "…", "conversation_id"?: "…" }`.

---

# 4. Admin APIs

POC (read-only): `GET /api/v1/admin/dashboard` · `GET /api/v1/admin/conversations` · `GET /api/v1/admin/conversations/{id}` · `GET /api/v1/admin/requests?type=&status=` · `GET /api/v1/admin/unresolved-questions`

V1 adds: knowledge sources CRUD (`GET/POST/PATCH/DELETE /api/v1/admin/knowledge-sources[…]`), canonical answers CRUD, `POST /api/v1/admin/requests/{id}:redeliver`, `POST /api/v1/admin/pii:reveal` (reason required, audited), privacy-request views, cursor pagination (`?cursor=&limit=`).

---

# 5. Model Tool Contracts (read-only)

**search_knowledge** — in: `{ query, categories?, max_results<=5 }` (audience is always forced to `public` by the application, not the model); out: `{ results: [{source_id, title, content, score, display_url}], search_status }`.

**get_canonical_answer** — in: `{ intent }`; out: `{ matched, canonical_answer_id?, content?, allowed_action_ids?, disclaimer?, mandatory_escalation? }`. Allowed actions are IDs the application resolves; the model cannot mint new actions.

**get_portal_information** — in: `{}`; out: approved portal URL + reset instructions from configuration.

There are no side-effecting model tools.

---

# 6. Error Contract

```json
{ "error": { "code": "CONVERSATION_BUSY", "message": "Please wait for the current response to complete.",
             "retryable": true, "request_id": "rid_01J…" } }
```

Codes: `INVALID_REQUEST`, `INVALID_EMAIL`, `UNAUTHORIZED_SESSION`, `CONVERSATION_NOT_FOUND`, `MESSAGE_TOO_LONG`, `CONVERSATION_BUSY`, `DUPLICATE_ACTION`, `RATE_LIMIT`, `MODEL_UNAVAILABLE`, `RETRIEVAL_UNAVAILABLE`, `PERSISTENCE_UNAVAILABLE`, `INTERNAL_ERROR`. Provider errors are never exposed directly. (Removed vs Rev 2: `DESTINATION_UNAVAILABLE` — external delivery no longer fails user requests — and workflow-specific codes.)

---

# 7. MongoDB Collections (7 total)

## conversations

```json
{
  "_id": "cnv_01JABC",
  "status": "active | completed | abandoned | blocked | deleted",
  "entry_page": "/services/ai-agents",
  "locale": "en-US",
  "consent_version": "privacy-2026-07",
  "active_run": { "run_id": "run_01J…", "started_at": "…" },   // or null
  "message_count": 7,
  "message_cap": 40,
  "outcome": "question_answered | service_recommended | strategy_call_requested | portal_opened | support_request_created | human_escalation_created | unresolved | abandoned | blocked",
  "unsupported_questions": [ { "question": "verbatim text", "at": "…" } ],
  "prompt_version": "sys-2026-07-01",
  "model": "…",
  "schema_version": 1,
  "started_at": "…", "last_activity_at": "…", "completed_at": null,
  "deletion_status": null,
  "messages": [
    {
      "id": "msg_01JUSER",
      "role": "user | assistant",
      "content": "…",
      "client_message_id": "cmid_9f3…",          // user messages only
      "status": "completed | failed | partial",
      "canonical_answer_id": "can_pricing_v3",    // assistant, when used
      "sources": [ { "source_id": "kbs_01J", "title": "LLM Selection", "display_url": "/approach/llm-selection" } ],
      "suggested_action_ids": ["strategy_call"],
      "usage": { "input_tokens": 1234, "output_tokens": 220 },
      "latency_ms": 1810,
      "error_code": null,
      "created_at": "…"
    }
  ]
}
```

Notes: intent/topic labels were not stored at POC. **As of V1.5 they are stored** on the conversation, computed asynchronously by the worker (never on the request path) — see [V1.5 additions](#v15-additions-to-the-data-model) below. Conversation state machine collapses to the statuses above — `awaiting_user`/`awaiting_confirmation` were UI states, not persistence states.

## requests

```json
{
  "_id": "req_01JXYZ",
  "type": "strategy_call | portal_support | human_escalation",
  "conversation_id": "cnv_01JABC",
  "idempotency_key": "…",                 // unique
  "reference": "REQ-8F3K",
  "contact": { "name": "…", "email": "…", "company": "…" },
  "fields": { },                           // per-type payload, validated by schema
  "consent_version": "consent-2026-07",
  "status": "received | delivering | delivered | delivery_failed",   // POC uses only 'received'
  "destination": "hubspot | zendesk | email | none",
  "external_reference": null,
  "delivery_attempts": 0,
  "last_delivery_error": null,
  "created_at": "…", "delivered_at": null
}
```

## knowledge_sources

`{ _id, title, category, audience: "public", language, approved: bool, lifecycle: "active|replaced|removed", indexing_status: "pending|indexed|failed", openai_file_id, vector_store_id, source_url?, version, owner, effective_date, review_date, checksum, created_at, updated_at }`

(Rev 2's five-state lifecycle, version linking, and rollback are deferred to V1.5+; V1 needs approved + active/replaced/removed.)

## canonical_answers

`{ _id, name, intent, audience: "public", content, disclaimer?, allowed_action_ids: [], mandatory_escalation: bool, status: "draft|approved", version, owner, effective_date, review_date }`

## feedback

`{ _id, conversation_id, message_id, rating, reason?, comment?, created_at }`

## jobs

`{ _id, type: "deliver_request | poll_indexing | retention_sweep | daily_aggregates", resource_id, status: "pending|running|done|failed|dead_letter", attempts, max_attempts, available_at, lock_owner?, lock_expires_at?, last_error?, created_at }`

Claim: `findOneAndUpdate({status:"pending", available_at:{$lte:now}}, {$set:{status:"running", lock_owner, lock_expires_at}})`.

## privacy_requests (V1)

`{ _id, type: "access|deletion", conversation_id?, requester_email, verification_status, status, created_at, completed_at }` — deletion touches one store.

Removed vs Revision 2: `message_projections`, `visitor_sessions`, `workflow_instances`, `tool_executions` (read-only tool calls are logged structurally, not persisted as business records), `strategy_call_requests`, `support_requests`, `sync_jobs`, `reconciliation_results`, `conversation_summaries`, `analytics_events` (POC analytics derive from conversations/requests), `dataset_candidates`, `evaluation_*` (golden set lives in the repo; result history added at V1.5), `admin_users` (POC single login; V1 identity provider).

## V1.5 additions to the data model

The V1.5 analytics wave added the following (all computed off the request path by the worker;
free text is PII-masked in the admin API). The code and the
[Analytics & insights](capabilities/analytics-and-insights.md) capability doc are the source of truth.

- **Conversation labels** — `conversation.labels` (topic + intent), computed asynchronously.
- **Conversation summary** — `conversation.summary` (a TL;DR + key points), **embedded** in the
  conversation document (not a separate collection — consistent with the removal above).
- **`insights_reports`** (new collection) — dated period snapshots (`<type>:<key>` id, e.g.
  `daily:2026-07-08`): question clusters, coverage, proposed FAQs, and an LLM narrative. The
  knowledge-gap ranking is a read-side view over these; it adds no new collection.
- **`daily_aggregates`** — dated count snapshots powering the dashboard/funnel.
- **`jobs.type`** additionally includes the analytics jobs: `label_conversations`,
  `generate_insights`, `summarize_conversations`, `daily_aggregates`.
- **Roles/audit (V1):** admin uses `admin`/`viewer` roles; every reveal/export and content/deletion
  action writes an append-only `audit` record (see [admin roles & audit](capabilities/admin-roles-and-audit.md)).

## Multi-provider model selection (OpenAI ↔ Anthropic)

The chat model provider is switchable at runtime from the admin portal. Provider isolation is
unchanged (invariant #4): a second adapter (`AnthropicMessagesAdapter`) lives behind the same
`ModelAdapter` protocol in `app/agent/adapter.py`; nothing provider-typed escapes it.

- **`app_settings`** (new collection) — a single document `_id: "model_provider"`:
  `{ active_provider: "openai" | "anthropic", updated_by, updated_at }`. Read by BOTH the API and
  the worker (short TTL cache) so a switch takes effect in every process without a restart. When
  the document is absent, the `MODEL_PROVIDER` env value is the default. No secrets are stored.
- **Endpoints:** `GET /api/v1/admin/model-provider` (admin or viewer) → `{ active, default, available }`
  (`available` = providers whose key is configured). `POST /api/v1/admin/model-provider`
  (**admin role only**, `{ provider, reason }`, reason required, audited) — rejects a provider that
  isn't in `available` with `INVALID_REQUEST`. `GET /api/v1/admin/system` also surfaces
  `active_model_provider`.
- **Audit action** `switch_model_provider` (target `app_setting` / `model_provider`).
- **Embeddings:** Anthropic has no embeddings API, so the Claude adapter reuses OpenAI embeddings
  for insights clustering — `OPENAI_API_KEY` remains required regardless of the active chat provider.
- **Promotion (invariant #15):** the golden set (`eval.run --provider anthropic`) gates the Claude
  config; switching in prod should follow a passing gate on the target provider.

## LLM usage & cost visibility

An admin Governance panel shows token usage + $ spend per provider / model / category, the
active model + a masked API key per provider, and a month-to-date budget with an alert.

- **`llm_usage`** (new collection) — a count-only daily rollup, `_id: "{date}:{provider}:{model}:{category}"`,
  `{date, provider, model, category, input_tokens, output_tokens, requests}`, written via `$inc`
  upserts by the worker's classify/embed calls (categories `summary`/`insights`/`labeling`/`embeddings`)
  through the adapter's `on_usage` hook. No PII → outside the retention sweep (like `aggregates`).
  **Chat + testing** usage is NOT recorded here — it's derived from conversation message `usage`
  (testing = `entry_page="eval"`), so it's never duplicated.
- **Endpoint:** `GET /api/v1/admin/usage?window=30` (admin or viewer) → totals + `by_provider`/
  `by_model`/`by_category` (tokens + $), `unpriced_models`, per-provider `{active, configured, model,
  key_last4}`, and `budget`. **`key_last4` is admins-only** (viewers get `null`; the full key is never
  sent/logged — invariant #5). Cost uses `app/domain/usage/pricing.py` + the `LLM_PRICING` env override;
  OpenAI/OpenRouter rates ship as PLACEHOLDERS and are flagged unpriced until set.
- **Budget alert** `llm_budget_exceeded` (warning) fires in `evaluate_alerts` when month-to-date spend
  ≥ `LLM_MONTHLY_BUDGET_USD` (0 = disabled); surfaced on `/monitoring` + the worker's alert log.

---

# 8. Indexes

conversations: `{status:1, last_activity_at:-1}` · `{outcome:1, started_at:-1}` · `{"messages.client_message_id":1}` (sparse) · TTL on abandoned anonymous conversations per approved retention (V1).
requests: `{idempotency_key:1}` unique · `{type:1, status:1, created_at:-1}` · `{"contact.email":1, created_at:-1}` · `{external_reference:1}` sparse.
knowledge_sources: `{openai_file_id:1}` unique sparse · `{lifecycle:1, category:1}` · `{review_date:1}`.
canonical_answers: `{intent:1, status:1}`.
jobs: `{status:1, available_at:1}` · `{lock_expires_at:1}`.
feedback: `{conversation_id:1}`.

---

# 9. Concurrency and Idempotency Summary

- One active run per conversation, enforced by the atomic lock in the conversation document; stale locks (> T min) cleared opportunistically.
- Duplicate `client_message_id` → replay original assistant message.
- Duplicate request `Idempotency-Key` → return original `request_id` and reference (200, `DUPLICATE_ACTION` detail).
- Delivery jobs are idempotent per request: before retrying, query the destination for the request reference; ambiguous outcomes park as `delivery_failed` for admin action — never a blind retry.

---

# 10. PII Contract

Public APIs may echo user-entered contact info during review only. Admin lists mask email/phone (`a***@acme.com`); reveal (V1) requires role + reason and is audited. Logs contain no message content, no full email/phone, no tool payloads, no tokens or credentials — structured logs reference IDs only. Analytics use pseudonymous IDs and aggregates.

---

# 11. V2+ Extension Points

Likely additions kept out of current schemas but anticipated by the repository layer: `tenant_id`, `account_id`, `authenticated_user_id`, `client_role`, `data_region`, `knowledge_store_ids`, `channel`, `human_agent_id`, `support_queue_id`; a separate per-tenant messages collection for uncapped threads. Every client endpoint validates identity, tenant, role, ownership, and action permission in the application.
