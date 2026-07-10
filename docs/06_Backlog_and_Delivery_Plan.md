# Cadre AI Customer Support Chatbot
## Implementation Backlog and Delivery Plan

**Status:** Current implementation planning baseline (Revision 3)
**Scope:** POC, public V1, V2+ direction

Priorities: **P0** = POC required · **P1** = public V1 required · **P2** = V1.5 · **P3** = V2+.

Definition of done: behavior implemented per contract; errors safe; no PII/secrets in logs; configuration documented; feature demonstrable **on the deployed environment**; golden set green where applicable.

---

# 1. Delivery Sequence

0. Walking skeleton deployed (SSE verified end to end).
1. MongoDB foundation and conversation document model.
2. Model adapter, agent loop, streaming.
3. Knowledge retrieval and canonical answers.
4. Golden evaluation harness.
5. Public chat UI (iframe).
6. Requests (all three types).
7. Read-only admin.
8. Privacy disclosures and masking.
9. POC hardening and demo.
10. V1: content approval, integrations, worker, roles, privacy operations, production deployment.

**Parallel track from day 0:** content owners assigned; approval cycles started for portal URL, destinations, security claims, pricing policy, AI Maturity details, privacy wording (Section 6). These have longer lead times than the engineering.

---

# 2. Epic E00 — Walking Skeleton (P0, week one) *(new)*

- Containerized FastAPI with health endpoint; static frontend shell; HTTPS on DigitalOcean.
- One hardcoded streamed SSE reply flowing browser → edge → API → browser on real infrastructure.
- Dev MongoDB connected; OpenAI key configured; structured logging with request IDs and no message content.
- CI pipeline building, testing, and deploying.

Acceptance: SSE deltas render progressively through the deployed routing path (no buffering). **This gates all further work.**

# 3. Epic E01 — Application Foundation (P0)

Modular project layout per Architecture §3; typed schemas and enums; ULID generation; environment configuration; safe structured logging; HMAC session tokens with key versioning; app-level rate caps (message length, per-conversation cap, per-IP creation cap). P1: feature flags, production config validation, version metadata.

# 4. Epic E02 — Conversation Foundation (P0)

Async MongoDB driver and repositories; conversation document with embedded messages; atomic lock + append + dedupe + cap in one `findOneAndUpdate`; stale-lock clearing; indexes per Contracts §8; transcript retrieval. P1: configurable expiration/abandonment sweep, TTL retention per approved periods.

# 5. Epic E03 — Agent Integration (P0)

Responses API adapter (send windowed history, stream, normalize usage/errors); versioned system prompt; read-only tool registration and in-process dispatch; unsupported-question escalation behavior; store per-message usage/latency/sources. P1: versioned model configuration, approved fallback model, tracing.

# 6. Epic E04 — Knowledge and Canonical Answers (P0)

Dev public Vector Store; **script/CLI corpus upload** with metadata recorded in `knowledge_sources`; search adapter with normalized results and forced `audience=public`; retrieval-failure fallback; canonical-answer repository seeded with pricing, security, AI Maturity, portal, company, services, industries, partners, case-study policy, and unsupported records; `get_canonical_answer` tool; mandatory-escalation flags honored. P1: staging/production stores, metadata filters, thresholds, promotion, admin knowledge UI (upload, replace, remove, approve), indexing-status polling job, canonical draft/approve lifecycle.

# 7. Epic E05 — Evaluation Harness (P0) *(new)*

`eval/` runner executing `golden_set.yaml` against the orchestrator; assertion types per Content §8; CI integration; failure report by case. P1: run against staging config as a deployment gate; result history. P2: evaluation console, dataset curation.

# 8. Epic E06 — Public Chat UI (P0)

iframe widget + loader script with origin-checked postMessage; launcher/panel/header with AI label; welcome + suggested prompts; privacy disclosure; composer with client message IDs; streaming renderer; suggested-action buttons; structured form panels (strategy call, portal support, escalation) with client-side drafts, review + consent + confirm; feedback control; error/busy/partial/cap states; mobile layout; keyboard navigation and screen-reader status for streaming. P1: reconnect via transcript endpoint, refined degraded states, accessibility audit, approved citation display if enabled.

# 9. Epic E07 — Requests (P0)

Unified `POST /api/v1/requests` with per-type schemas; email validation; consent-version recording; idempotency; reference generation; escalation records preserving verbatim question + safe summary; success/failure/duplicate responses. P1: delivery jobs to approved CRM/scheduler and ticketing destinations; external references; bounded retries with by-reference ambiguity resolution; dead-letter status; admin redeliver; category routing where required.

# 10. Epic E08 — Admin (P0 read-only)

Single protected login behind HTTPS; overview metrics (conversations, requests by type, unresolved count, feedback rate); conversation list + detail (transcript, sources, outcome); request list; unresolved-question list; masked PII throughout. P1: production identity provider; **admin and viewer roles**; PII reveal with reason + audit; audit log; filters and cursor pagination; delivery-failure view; privacy-request view.

# 11. Epic E09 — Privacy (P0 disclosures)

Chat disclosure with recorded version; contact-submission consent with recorded version; credential warnings on forms; masking; log hygiene verification; documented manual deletion procedure (single-store). P1: legal-approved wording; retention classes + sweep job; verified deletion requests; reveal/export audit; privacy-request management. P2: dataset-candidate workflow with redaction and reviewer approval.

# 12. Epic E10 — Background Jobs (P1 mostly)

P0: job model with atomic claim (needed only if indexing polling is jobized; otherwise inline). P1: dedicated worker process; delivery retry; lock expiration; retry limits; dead-letter; retention cleanup; daily aggregates; knowledge review reminders.

# 13. Epic E11 — V1 Deployment

Staging + production environments; load balancer with SSE re-verified; multiple stateless instances as needed; secrets management; edge rate limits + WAF; monitoring and alerts; production MongoDB (Atlas vs self-hosted decision) with backups and restore test; separate staging/production OpenAI resources.

# 14. Epic E12 — V2+ Platform (P3, unchanged direction)

Client authentication, tenancy, roles; tenant-aware repositories and a separate messages collection for uncapped threads; private Vector Stores selected by the application; client tools with per-call validation; human takeover with WebSockets; regional retention. V2+ remains a separate trust tier. (Provider-neutral history: already satisfied by ADR-014.)

The authenticated capability set and phased rollout (Phases 0–4) are specified in `docs/07_V2_Authenticated_Capability_Plan.md`; the durable decisions are **ADR-020** (agent runtime) and **ADR-021** (authenticated trust tier) in doc 03.

---

# 3. Milestones

**M0 — Deployed skeleton (week 1).** E00 complete; SSE verified in production path.

**M1 — Grounded conversation.** Multi-turn streamed chat on deployed env; retrieval + canonical answers; unsupported fallback; golden-set harness running with initial cases.

**M2 — Business workflows.** All three request types with review, consent, idempotency, references; suggested actions wired.

**M3 — Visibility and privacy.** Read-only admin; unresolved questions; disclosures, consent versions, masking; log hygiene verified.

**M4 — POC complete.** Six scenarios demonstrable; golden set green; abuse caps active; manual deletion procedure documented. → POC→V1 gate review.

**M5 — Public V1.** Approved content published; CRM/ticket delivery with retry and failure views; identity provider + roles; retention/deletion operational; staging/production; edge controls; monitoring. → V1 public gate review.

---

# 4. POC Minimum Build (exit checklist)

Deployed skeleton with verified SSE · conversation document model with atomic turn loop · Responses adapter + versioned prompt + read-only tools · dev Vector Store with scripted corpus · seeded canonical answers · unified requests endpoint (three types) with idempotency and references · iframe chat UI with forms, feedback, error states · read-only admin (conversations, requests, unresolved, metrics, masked PII) · privacy disclosure + consent versions · abuse caps · golden set green · documented manual deletion.

# 5. Removed from Revision 2 backlog

OpenAI Conversations mapping; transcript projection and all sync states; manual + automated reconciliation; sync-health dashboards; workflow state machine and draft persistence; `workflow_instances`, `sync_jobs`, `message_projections`, `visitor_sessions`, `tool_executions` collections; POC knowledge-management UI; five admin roles (two remain); per-message intent/topic classification (V1.5, async); Agents SDK integration.

---

# 6. Remaining Decisions

| Decision | Needed before | Owner to assign |
|---|---|---|
| Official portal URL and reset instructions | POC demo realism; V1 launch | Client Success |
| Strategy-call destination (CRM/scheduler) | V1 delivery jobs | Sales |
| Support destination and routing | V1 delivery jobs | Client Success |
| Admin identity provider | V1 admin | Engineering/IT |
| Privacy and consent wording | Public launch | Legal |
| Retention periods | Public launch | Legal/Privacy |
| Approved security claims | Public launch | Security/Legal |
| Pricing response policy (final wording) | Public launch | Sales/Leadership |
| AI Maturity Index details | Public launch | Product owner |
| Public citation behavior | Citation UI (V1) | Product/Marketing |
| Approved case studies | V1 content | Marketing |
| MongoDB Atlas vs self-hosted | V1 infrastructure | Engineering |
| Initial model + fallback | Agent configuration | Engineering |
| Message cap / session expiry values | POC config (defaults: 40 msgs, 24h) | Product |
