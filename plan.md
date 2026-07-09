# plan.md — Cadre AI Support Chatbot (V1 build)

V1 makes the shipped POC **safe, reliable, and operable for public use**. It builds ON the
committed POC (phases 0–8, `docs/archive/plan_POC.md`) — do not rebuild that; extend it.

Execute phases **in order**. Each ends with a ✅ CHECKPOINT: run the verification, fix
anything red, commit with the listed message, then stop and summarize before continuing.
Phases marked ⚡ contain subtasks safe to parallelize with subagents (disjoint files,
frozen contracts). The exit bar is the **V1 public gate** (doc 02 §8), realized in Phase V8.

Authoritative references: V1 scope `docs/02_Release_Capability_Plan.md` §4 + the **P1**
items in `docs/06_Backlog_and_Delivery_Plan.md`; contracts `docs/04`; architecture/ADRs
`docs/03`; content + golden set `docs/05`; invariants `CLAUDE.md`.

## Blocking decisions (doc 06 §6 — need owners; start these now, in parallel)

V1 depends on inputs owned outside engineering. For a blocked phase, **build against the
interface with a fake/placeholder and flag the decision** — do not stall the whole track.

| Decision | Blocks | Owner |
|---|---|---|
| Strategy-call destination (CRM/scheduler) | Phase V4 | Sales |
| Support destination + routing | Phase V4 | Client Success |
| Admin identity provider | Phase V5 | Engineering/IT |
| Privacy/consent wording; retention periods | Phase V6 | Legal/Privacy |
| Approved security claims; pricing policy; case studies | Phase V2 (content) | Security/Sales/Marketing/Legal |
| AI Maturity Index details | Phase V2 (content) | Product owner |
| Official portal URL + reset instructions | Phase V2/V7 | Client Success |
| Public citation behavior (display on/off) | Phase V7 | Product/Marketing |
| MongoDB Atlas vs self-hosted | Phase V8 | Engineering |
| Initial model + fallback | Phase V1 | Engineering |

**Parallel track from day 0:** content owners run approval cycles (security claims, pricing
wording, AI Maturity details, portal URL, case studies, privacy wording). Longer lead time
than the engineering — do not let it become the critical path.

---

## Phase V0 — V1 foundation and staging environment

Goal: split configuration into environments and stand up a real **staging** deploy, so every
later phase is demonstrable on deployed infra (not just localhost).

1. `app/core/config.py`: per-environment settings (staging/production) for `MONGO_URI`,
   OpenAI project key, and Vector Store IDs; production config validation (extend the
   fail-closed secret guard to require all prod inputs); `app_version`/build metadata on
   `/healthz`; feature flags for V1-in-progress surfaces.
2. Secrets management approach documented (no secrets in repo/logs; injected per env).
3. Deploy the current app to **staging** on the target host; re-verify SSE renders
   progressively through the load-balancer path (the E00 skeleton test, now on staging).
4. CI: build/test/lint/typecheck on every push; deploy to staging on main.

✅ CHECKPOINT V0 — staging URL serves the widget with streaming verified through the LB;
`pytest`/`mypy`/`ruff` green; prod-config validation test asserts a missing prod secret
fails startup. Commit: `chore: V1 foundation and staging environment`
> Blocked-on: none (uses placeholders for prod-only inputs).

---

## Phase V1 — Agent controls and retrieval hardening ⚡

Goal: versioned prompts/model with fallback, tracing, and retrieval quality controls; the
golden gate wired into deployment.

1. Versioned prompt registry (already `prompts/sys-vN.md`) + versioned model configuration
   (approved model + **approved fallback**); the assistant message already records the
   prompt/model version — surface both in admin.
2. `app/agent/adapter.py`: on `MODEL_UNAVAILABLE`, retry once on the fallback model; add
   tracing hooks (per-turn trace id, latency, token usage — **no PII, no content**).
3. Retrieval: metadata filters (audience stays forced `public`; add category filters) and a
   **relevance threshold** that drops low-score hits before grounding; keep the
   `RETRIEVAL_UNAVAILABLE` fallback.
4. Staging + production Vector Stores; `upload_knowledge.py` targets an env; document the
   staging → production **promotion** step (never edit prod content directly).
5. CI: `python -m eval.run` runs against the **staging config** as a deployment gate.

✅ CHECKPOINT V1 — golden set green on staging config; a test forces `MODEL_UNAVAILABLE` and
asserts the fallback path; a low-relevance hit is filtered out of grounding.
Commit: `feat: versioned agent config, model fallback, and retrieval controls`
> Blocked-on: initial model + fallback (Engineering).

---

## Phase V2 — Content approval lifecycle and mid-conversation booking ⚡

Goal: approved-content lifecycle, plus fix the top POC gap — the booking form must surface
mid-conversation, not only from the welcome chip.

1. Canonical approval lifecycle — **most of this already ships** (verify before building):
   `canonical_answers` already has `status` (`draft`|`approved`, default draft),
   `owner`/`effective_date`/`review_date`, the `intent_status` index, and
   `get_canonical_answer` already serves **only `approved`** (contracts §5/§8). The real V1
   gap is small: let `seed_canonical.py`/import write `draft` (today it stamps `approved`),
   and add the admin **approve** action (built in Phase V5) that flips draft → approved.
2. **Booking action fix (top V1 item, DECISIONS_LOG):** add a canonical answer for the
   booking/scheduling intent whose `allowed_action_ids` includes `strategy_call`; add that
   intent to the `get_canonical_answer` tool + system-prompt enum and route
   "book / connect / schedule a call" phrasings to it, so the reply always carries the
   `strategy_call` chip → the widget opens the form. No new tool (keeps invariant 2).
3. Ensure `knowledge_sources` carries review metadata (owner, review-by); the scheduled
   knowledge-review reminder **job** that reads it is built in Phase V3.
4. Golden set: add a mid-conversation booking case (`must_offer_action: strategy_call`) and a
   draft-not-served case.

✅ CHECKPOINT V2 — golden green incl. the booking case; a `draft` canonical answer is NOT
served; asking to "book a call" three turns in surfaces the form. Run `eval.run` (content
change). Commit: `feat: content approval lifecycle and mid-conversation booking action`
> Blocked-on: final approved wording (parallel content track) — engineer against seeded drafts.

---

## Phase V3 — Background worker and job infrastructure

Goal: the dedicated worker process and durable job model everything async sits on. Build this
BEFORE delivery/retention — they are job types on top of it.

1. `jobs` collection + Pydantic job model **exactly per contracts §7** (`type`, `resource_id`,
   `status: pending|running|done|failed|dead_letter`, `attempts`, `max_attempts`,
   `available_at`, `lock_owner`, `lock_expires_at`, `last_error`); **atomic claim** via the §7
   `findOneAndUpdate({status:"pending", available_at:{$lte:now}}, …)`; indexes
   `{status:1, available_at:1}` + `{lock_expires_at:1}` (§8). Mirrors the turn-lock discipline.
2. `app/worker.py`: a claim-and-run loop with graceful shutdown; per-job-type retry limits,
   exponential backoff, `lock_expires_at` lease expiry, and dead-letter transition.
3. Move the stale-lock sweep into a scheduled worker job (still available as the CLI script).
4. Scheduled jobs: **daily aggregates** (conversation/request/feedback counts for the admin
   overview); **knowledge-review reminders** (surface `knowledge_sources` past `review_date`);
   **abandonment/expiration sweep** (mark inactive conversations abandoned — configurable;
   distinct from the retention *deletion* in V6).
5. Monitoring hooks: health, queue depth, dead-letter count (metrics only — no PII).
6. Tests: two workers claim the same job → exactly one runs; retry→backoff→dead-letter;
   crash mid-job → `lock_expires_at` passes → reclaimed.

✅ CHECKPOINT V3 — worker runs against staging; concurrency-claim test green; a failing job
dead-letters after its retry limit; daily aggregates written; a source past its `review_date`
is flagged. Commit: `feat: background worker and durable job model`
> Blocked-on: none.

---

## Phase V4 — Business delivery integrations

Goal: deliver each request to its external destination via idempotent async jobs on the V3 worker.

1. `app/domain/delivery/`: destination adapters — strategy-call → CRM/scheduler;
   portal-support + escalation → ticketing. **Provider-isolated** (invariant 4); IDs/errors
   normalized; `FakeDeliveryClient` for tests.
2. Creating a request enqueues a delivery job **idempotently by `request_id`** (an external
   system is called at most once; retries replay).
3. Bounded retries with backoff → **dead-letter**; store the returned **external reference**
   on the request (`{external_reference:1}` sparse index, contracts §8). Per contracts §7,
   **before a retry query the destination for the request reference** — ambiguous outcomes
   park as `delivery_failed` for admin action, never a blind retry and **never a re-prompt**
   (invariant 11). **Category routing** where required.
4. Request status reflects delivery (`received` → `delivering` → `delivered` / `delivery_failed`).
5. Failure-path tests (a V1 gate requirement): transient error → retry → success; permanent
   → dead-letter; duplicate enqueue → single external call; external ref persisted.

✅ CHECKPOINT V4 — each request type delivers to its faked destination; retry, dead-letter,
and idempotent replay all tested; external reference stored and shown only in admin.
Commit: `feat: asynchronous request delivery with retries and dead-letter`
> Blocked-on: destinations selected (Sales, Client Success) — ship against `FakeDeliveryClient` + a config-selected adapter until then.

---

## Phase V5 — Admin V1: roles, audit, knowledge UI, delivery ops ⚡

Goal: production identity, two roles, audit, and the operational admin surfaces.

1. Production identity provider; roles **`admin` and `viewer`** enforced per route; masking
   stays the default.
2. `app/domain/audit/`: **PII reveal/export requires a reason and writes an append-only audit
   record**; content-approval and deletion actions are audited too. A `viewer` cannot reveal.
3. Lists gain filters + **cursor pagination**.
4. **Delivery-failure dashboard**: dead-letter view + a `redeliver` action (an admin write
   that re-enqueues a job — audited).
5. **Knowledge management UI**: upload / replace / remove / **approve** (drives the Phase V2
   lifecycle); indexing-status polling.
6. Privacy-request management view (feeds Phase V6).

✅ CHECKPOINT V5 — a `viewer` is denied reveal (403) and the attempt/authorized-reveal are
audited; `redeliver` re-enqueues a dead-lettered job; approving a draft publishes it.
Commit: `feat: role-controlled admin with audit, knowledge UI, and delivery ops`
> Blocked-on: admin identity provider (Engineering/IT) — build against an IdP interface + a dev stub.

---

## Phase V6 — Privacy operations: retention, verified deletion, audit

Goal: legal-grade privacy operations on the V3 worker.

1. Legal-reviewed chat disclosure + contact-submission consent, with **recorded versions**.
2. **Retention classes/periods** enforced by a scheduled worker sweep + TTL on abandoned
   anonymous conversations (contracts §8), per approved periods.
3. **Verified deletion requests** recorded in a `privacy_requests` collection (contracts §7):
   verify the request, then execute single-store deletion across
   `conversations`/`requests`/`feedback` (+ documented provider-retention terms); the whole
   action is audited. No ad-hoc deletes on the request path (invariant 13).
4. Reveal/export audit surfaced in admin; export controls.

✅ CHECKPOINT V6 — the retention sweep removes data past its class period; a verified deletion
request purges a subject across all collections and writes an audit record; the privacy notice
matches actual handling. Commit: `feat: retention, verified deletion, and privacy operations`
> Blocked-on: retention periods + privacy/consent wording (Legal/Privacy).

---

## Phase V7 — Experience and accessibility ⚡

Goal: production-grade widget UX.

1. **Reconnect + transcript recovery**: on reload/stream drop, resume the conversation from
   the transcript endpoint (session token in memory; re-create only on true expiry).
2. Refined degraded states: expired-session recovery, cap UX, retrieval-degraded copy — exact
   wording from docs 05 §6.
3. **Accessibility pass**: keyboard navigation, focus management, screen-reader **status for
   streaming** (`aria-live`), contrast, reduced-motion; automated axe check + manual audit.
4. Production website integration; production portal + privacy links.
5. **Citation display (flag-gated):** if public citation behavior is approved, render approved
   sources on grounded answers (the assistant message already stores `sources`); otherwise ship
   with the flag off. Decision: "Public citation behavior" (Product/Marketing).

✅ CHECKPOINT V7 — a mid-conversation reload restores the transcript and resumes; axe +
keyboard audit clean; a screen reader announces streaming progress and completion.
Commit: `feat: reconnect, degraded states, and accessibility pass`
> Blocked-on: production portal + privacy URLs (Client Success / Legal); public citation
> behavior (Product/Marketing) — ship the citation flag off until decided.

---

## Phase V8 — Production deployment and V1 public gate

Goal: production infrastructure and the **V1 public gate** (doc 02 §8).

1. Separate **staging and production**; load balancer with SSE re-verified; multiple stateless
   FastAPI instances as needed; the worker deployed and supervised.
2. **Production MongoDB** (Atlas vs self-hosted — decision) with backups + a **tested
   restore**; production indexes + connection limits.
3. **Edge rate limiting + WAF**; secrets management; separate staging/production OpenAI
   resources and Vector Stores.
4. Monitoring + alerts live (error rate, dead-letter, latency, queue depth).
5. Golden set green on the **production configuration**; published approved content.

✅ CHECKPOINT V8 (V1 public gate — doc 02 §8) — approved content published; integrations
verified with failure-path tests; role-controlled admin; retention + deletion operational;
production MongoDB with tested restore; staging/production separated; edge controls on;
monitoring live; privacy notice matches handling; golden set green on prod config. Write
`docs/V1_EXIT_REPORT.md` mapping each gate item to its evidence.
Commit: `chore: V1 production deployment and public gate`
> Blocked-on: MongoDB Atlas vs self-hosted (Engineering).

---

## Backlog (V1.5 / V2+ — do NOT build during V1)

V1.5: semantic topic clustering, async intent/topic labeling, conversation summaries,
knowledge-gap ranking, evaluation console + **golden-run result history** + dataset curation
(with PII redaction) — contracts §7 places eval result history at V1.5, resolving the doc 06
E05 wording; AI Maturity mini-assessment, funnel analytics. V2+: authenticated clients, tenancy/roles, tenant-scoped
retention, private Vector Stores, client tools with per-call authz, human takeover
(WebSockets), regional controls. See `docs/02_Release_Capability_Plan.md` §5–6.

---

## V1.5 — Conversation Insights (clustering + gap analysis + proposed FAQs)

Goal: turn ended conversations into an operator-facing **insights report** — *what are people
asking, do we cover it, and what should we add?* Scheduled daily + manual kickoff. Builds ON the
labeling slice (labels/transcripts/`adapter.classify`/worker/canonical draft→approved gate).

**Decisions (owner: Trevor, 2026-07-09):** clustering = **hybrid** (embeddings pre-group → LLM
name/analyze/propose); uncovered high-volume clusters **auto-draft a canonical answer** (status
`draft`, never served) into the **existing approve gate** — no auto-publish. Embeddings are an
**ephemeral compute input** (cluster in memory, persist only results; no vectors in Mongo).

Slice A — Foundations ⬜
1. `app/domain/insights/`: models (`QuestionCluster`, `InsightsReport`, `Coverage`), repository
   (`insights_reports` dated snapshots, like `daily_aggregates`).
2. `cluster.py`: pure-function cosine/agglomerative grouping over embeddings (threshold + min size).
3. `adapter.embed()` (provider-isolated OpenAI embeddings) + Protocol + FakeAdapter deterministic stub.
4. Config: cadence, window, batch cap, embed model, similarity threshold, min cluster size, time budget.
✅ CHECKPOINT A — ruff/mypy/pytest green; cluster unit tests group deterministic vectors correctly.

Slice B — Pipeline + job + manual kickoff ⬜
1. `run_generate_insights`: window of ended+labeled convos → extract representative question →
   embed → cluster → per cluster {name, coverage vs canonical+KB, demand count, proposed draft} →
   LLM insights summary → store dated `InsightsReport`. Wall-clock-budgeted + idempotent per date.
2. Worker: daily `_SCHEDULE` entry + dispatch. Manual `POST /admin/insights/run` (admin, audited).
3. Auto-draft: uncovered high-volume cluster → canonical **draft** (reuse canonical upsert) linked to
   the cluster; served only after the existing admin Approve.
4. Failure-path + idempotency tests.
✅ CHECKPOINT B — job produces a report on staging; a proposed FAQ lands in the canonical draft queue.

Slice C — Admin Insights dashboard ⬜
1. `GET /admin/insights` (latest + list). New admin **Insights** tab: clusters (name, count,
   coverage, sample questions), proposed FAQs → link to Approve, and the LLM insights summary.
2. Frontend tests.
✅ CHECKPOINT C — the Insights tab renders clusters + summary; proposed FAQ approvable from the gate.

Slice D — Adversarial review + deploy + verify ⬜ (review workflow → gate → staging → verify live).
