# Cadre AI Customer Support Chatbot — Planning Package (Revision 3)

> **This is the design/planning package (docs `01`–`06`).** The project is now **built** (V1 + V1.5).
> For the *shipped* system, start at the **[repository README](../README.md)** and the
> **[Capabilities Catalog](capabilities/)** (one doc per feature). Where the plan and the build differ,
> the catalog reflects reality. A full index of everything in this folder is at the bottom of this file.

This package supersedes Revision 2. It reflects a design review focused on shipping the POC and public V1 quickly, and it makes several large architectural changes.

## Included documents

1. **01_Product_Requirements_Document.md** — product goals, scenarios, requirements (revised P0 scope)
2. **02_Release_Capability_Plan.md** — POC / V1 / V1.5 / V2+ capability sets (POC materially slimmed)
3. **03_Architecture_and_Decision_Records.md** — merged technical design, system architecture, and ADRs (replaces prior docs 04, 05, 06)
4. **04_API_and_Data_Contracts.md** — endpoints, document schemas, indexes (rebuilt)
5. **05_Conversation_and_Content_Specification.md** — identity, canonical answers, golden evaluation set (content largely retained; eval set added)
6. **06_Backlog_and_Delivery_Plan.md** — epics and milestones (deploy-first sequencing)

Nine documents were consolidated to six. The UX specification's normative content (flows, error states, accessibility) is folded into docs 01, 03, and 05 rather than maintained separately.

## Everything else in this folder

Beyond the planning package, `docs/` now holds the shipped-system and operational documentation:

- **Capabilities** — [`capabilities/`](capabilities/) — one doc per feature (what / why / status / future). **Start here for the built system.**
- **Architecture (C4)** — [`architecture/`](architecture/) — system context → containers → components, the 13-collection data model, runtime data flows, and cross-cutting/trust-boundary concerns (Mermaid diagrams).
- **Operations** — [DEPLOY_STAGING](DEPLOY_STAGING.md) · [DEPLOY_PROD](DEPLOY_PROD.md) · [RUNBOOK_PROD](RUNBOOK_PROD.md) · [RUNBOOK_POC](RUNBOOK_POC.md) (historical).
- **Compliance** — [PRIVACY_NOTICE](PRIVACY_NOTICE.md) (DRAFT, pending Legal) · [SECURITY_REVIEW_V1](SECURITY_REVIEW_V1.md).
- **Quality** — [EVAL_TESTER_GUIDE](EVAL_TESTER_GUIDE.md) (the golden-set gate + dev tool).
- **History & decisions** — [V1_EXIT_REPORT](V1_EXIT_REPORT.md) · [POC_EXIT_REPORT](POC_EXIT_REPORT.md) · [DECISIONS_LOG](DECISIONS_LOG.md) · [archive/](archive/).
- **Content corpus** — [knowledge/](knowledge/) — the approved markdown pushed to the Vector Store.

## Summary of major changes from Revision 2

| # | Change | Replaces | Why |
|---|---|---|---|
| 1 | **MongoDB is the single source of truth for conversation history.** Model calls are stateless: the application sends the windowed transcript on each turn via the OpenAI Responses API. | ADR-004 (OpenAI Conversations authoritative), ADR-005 (projection), ADR-010 (eventual consistency) | Eliminates the entire sync/reconciliation subsystem, makes privacy deletion a single-store operation, and delivers the "provider-neutral history" previously deferred to V2+. Token cost of resending short public transcripts is negligible. |
| 2 | **Messages are embedded in the conversation document.** | message_projections collection, cross-document sequencing, separate run-lock mechanism | Public chats are short and capped. Single-document atomicity solves locking, deduplication, and ordering in one `findOneAndUpdate`. |
| 3 | **Side effects never pass through the model.** The agent may only *offer* a workflow; the browser submits structured forms directly to typed endpoints. Model tools are read-only. | Workflow state machine (start/PATCH/review/submit), workflow_instances collection, model-invoked submission tools | Removes an entire API surface and state machine; strengthens the trust boundary (the model is not in the write path at all). |
| 4 | **One unified `requests` collection and endpoint** for strategy-call, portal-support, and escalation, with asynchronous best-effort external delivery. | strategy_call_requests, support_requests, escalation records; synchronous delivery semantics | The three request types share shape and lifecycle. Local persistence is the user-facing success criterion; delivery status is an admin concern. |
| 5 | **Stateless signed session tokens.** | visitor_sessions collection | One less collection; horizontal scaling unchanged. |
| 6 | **Golden evaluation set is a P0 deliverable and a launch gate.** | Evaluation deferred to V1.5 | Cheapest safety net for an LLM product; catches prompt/model regressions and prohibited-claim leaks before users do. |
| 7 | **Basic abuse caps at POC** (per-conversation message cap, per-IP creation cap, message length limit). | Rate limiting deferred entirely to V1 | An unmetered public LLM endpoint is a cost and abuse liability from day one. |
| 8 | **Deployment is Milestone 0.** A walking skeleton (health check + one streamed reply) runs on DigitalOcean in week one to verify SSE through the real hosting path. | Deployment at Milestone 5 | SSE buffering through load balancers is a known failure mode; discover it first, not last. |
| 9 | **Knowledge management UI deferred to V1.** POC uploads the small corpus via script/CLI. | POC admin knowledge upload/removal UI | The POC corpus is 10–30 documents; a UI adds no proof value. |
| 10 | **Direct Responses API adapter instead of the Agents SDK.** | ADR-003 | With one agent, read-only tools, and app-owned history, the agent loop is ~100 lines; the SDK's orchestration value doesn't offset the coupling. Revisit if multi-agent needs emerge. |
| 11 | **iframe embed decided explicitly.** | Unspecified embedding | Isolation from host-page CSS/JS, simpler CSP, contained token scope. |

## Current architecture summary

- Public chat widget (iframe embed) and admin UI
- FastAPI modular monolith on DigitalOcean; REST + Server-Sent Events
- MongoDB: single system of record (conversations with embedded messages, requests, knowledge metadata, canonical answers, feedback)
- OpenAI Responses API through a thin internal adapter; stateless per-turn calls with windowed history
- OpenAI Vector Stores for managed hybrid retrieval over approved public content
- Read-only model tools; all side effects via typed application endpoints with client confirmation and idempotency keys
- MongoDB-backed background jobs (delivery retry, retention); no Redis/broker
- Golden evaluation set run in CI; required gate for prompt, model, or canonical-answer changes
- Privacy: layered disclosure, PII masking, single-store deletion, no raw transcripts in logs

## Explicitly excluded

Detailed test plans beyond the golden set, launch execution, post-release runbooks, and incident response remain out of scope for this package.
