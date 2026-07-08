# Cadre AI Customer Support Chatbot
## Release Capability Plan

**Status:** Approved planning baseline (Revision 3)
**Releases:** POC, V1, V1.5, V2+

---

# 1. Release Principles

1. The POC proves the six core scenarios end to end **on real infrastructure** — nothing more.
2. V1 makes the POC safe, reliable, and operable for public use.
3. V1.5 improves intelligence and efficiency without changing the trust boundary.
4. V2+ introduces authenticated clients, tenancy, private knowledge, and human support — a separate trust tier.
5. Features do not move earlier merely because they are technically possible.
6. Content approval runs in parallel with engineering from day one.

---

# 2. POC Capability Set

## 2.1 Public chat

- iframe-embedded launcher and panel; mobile-responsive.
- AI identity and privacy disclosure; suggested prompts.
- Text input, streamed responses, multi-turn context, suggested actions.
- Feedback (helpful / not helpful with reason).
- Error, retry, and partial-stream states.
- Message length limit; per-conversation message cap; per-IP creation cap.

## 2.2 Supported scenarios

Company overview and industry fit; service discovery; AI Maturity Index; LLM selection and partners; general data security; strategy-call request; portal guidance and portal-support request; human escalation; unsupported-question fallback.

## 2.3 Agent and retrieval

- One primary agent via the Responses API adapter; stateless per-turn calls with windowed history.
- Read-only tools: `search_knowledge`, `get_canonical_answer`, `get_portal_information`.
- One development public Vector Store, default hybrid retrieval, corpus uploaded by script.
- Canonical answers for all sensitive subjects; deterministic unsupported-question escalation.

## 2.4 Business workflows

- Assistant offers workflows; browser renders structured forms.
- Client-side drafts; review and consent; single idempotent submit endpoint.
- Unified local `requests` records with references; delivery to external systems is out of POC scope (placeholder destination = stored locally, visible in admin).

## 2.5 Admin (read-only)

- Single protected login (shared credential or basic auth behind HTTPS).
- Overview metrics; conversation list and detail; request list; unresolved-question list; masked PII.

## 2.6 Privacy

- Chat disclosure and privacy link; contact-submission consent with recorded version.
- PII masking in lists; no raw messages or PII in logs; credential warning.
- Manual, documented deletion procedure (single store makes this trivial).

## 2.7 Evaluation and deployment

- Golden evaluation set (30–50 cases) runnable from CI; passing is a POC exit criterion.
- Deployed on DigitalOcean from week one: one FastAPI instance, one frontend, development MongoDB, one OpenAI project and Vector Store, HTTPS, SSE verified through the hosting path.

---

# 3. POC Explicit Exclusions

Knowledge management UI (script upload instead); workflow draft persistence and server-side workflow state machine; sync/reconciliation of any kind; automated external delivery; production CRM/tickets; multiple API instances; dedicated worker; RBAC beyond one login; automated deletion workflows; intent/topic classifiers; conversation summaries; semantic clustering; private stores; live agents; multi-region; Redis/broker.

---

# 4. Public V1 Capability Set

## 4.1 Experience

Production-approved content; production website integration; browser reconnect and transcript recovery; refined degraded states; accessibility pass (keyboard, focus, screen-reader status for streaming, contrast, reduced motion); production portal and privacy links.

## 4.2 Agent controls

Versioned prompts and model configuration; approved model plus fallback; tracing; retrieval metadata filters and relevance thresholds; staging and production Vector Stores with controlled promotion; golden-set gate wired into deployment.

## 4.3 Business integrations

Approved strategy-call destination (CRM/scheduler) and support destination (ticketing); asynchronous delivery jobs with retry limits, dead-letter state, external references, and admin visibility of failures; routing by request category where required. Ambiguous outcomes are resolved by the delivery job, never by re-prompting the user.

## 4.4 Persistence and operations

Production MongoDB (Atlas or replica set — decision required) with backups and restore testing; production indexes and connection limits; dedicated background worker (delivery retry, retention, daily aggregates, knowledge review reminders); monitoring and alerts.

## 4.5 Admin

Production identity provider; **two roles: admin and viewer** (further roles only with demonstrated need); PII reveal with reason and audit; audit logs for reveal/export/content/deletion; filters and cursor pagination; knowledge management UI (upload, replace, remove, approve flag); privacy-request management; delivery-failure dashboard.

## 4.6 Privacy

Legal-reviewed disclosure and consent; defined retention classes and periods with automated jobs; verified deletion requests (single-store deletion plus documented provider retention terms); reveal auditing; export controls.

## 4.7 Deployment

Staging and production environments; load balancer with SSE validated; multiple stateless FastAPI instances as needed; secrets management; edge rate limiting and WAF; separate staging/production OpenAI resources.

---

# 5. V1.5 Capability Set

Semantic topic clustering; intent/topic labeling (async, not in the request path); conversation summaries; knowledge-gap ranking; expanded evaluation console; AI Maturity mini-assessment; funnel analytics; dataset-candidate workflow with PII redaction and reviewer approval; automated content-review reminders; internal response suggestions. None of these change the public trust model.

---

# 6. V2+ Direction (unchanged in substance)

Client authentication, tenant resolution and roles, tenant-scoped conversations and retention, private Vector Stores per security domain (application-selected, never model-selected), client tools with per-call tenant/role validation, human takeover with WebSockets, regional and enterprise controls, dedicated analytics/event infrastructure only when justified.

Note: because V1 history is already provider-neutral (MongoDB-owned), the V2+ "provider-neutral conversation layer" work item is eliminated.

---

# 7. Capability Matrix

| Capability | POC | V1 | V1.5 | V2+ |
|---|---|---|---|---|
| Public Q&A (grounded + canonical) | Yes | Production | Improved | Yes |
| Conversation history | MongoDB (sole) | Same | Same | Tenant-aware |
| Vector Store | One dev store | Staging + production | Better evaluation | Public + private |
| Canonical answers | Basic records | Approved lifecycle | Expanded | Tenant/region variants |
| Requests (call/support/escalation) | Stored locally | Delivered to CRM/tickets | Enhanced routing | Account-aware |
| Admin | Read-only, one login | Two roles, audit | Advanced analytics | Account intelligence |
| Knowledge management | Script upload | Admin UI + approval | Review automation | Multi-store governance |
| Evaluation | Golden set in CI | Release gate | Console + datasets | Same |
| Abuse controls | App-level caps | Edge + WAF | Same | Same |
| Privacy | Disclosure, masking, manual delete | Retention, verified deletion, audit | Dataset curation | Client policies |
| Background jobs | In-process | Dedicated worker | More analytics | Broker only if needed |
| Multi-tenancy / live chat / multilingual | No | No | No | Yes / optional / optional |

---

# 8. Promotion Gates

**POC → V1 planning:** six scenarios pass on the deployed environment; golden set green; retrieval quality acceptable; content gaps enumerated with owners; CRM/ticket destinations selected; admin identity approach selected; privacy owner assigned.

**V1 public gate:** approved content published; production integrations verified with failure-path tests; role-controlled admin; retention and deletion operational; production MongoDB with tested restore; staging/production separated; edge abuse controls on; monitoring live; privacy notice matches actual data handling; golden set green on the production configuration.

**V2 design gate:** tenant/authorization model approved; client retention defined; private-knowledge isolation selected; tool authorization formally designed; human-support ownership defined; regional/contractual requirements known.
