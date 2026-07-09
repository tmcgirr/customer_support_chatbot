# Capabilities Catalog

One short doc per capability of the Cadre AI support chatbot — written for a **product
manager** onboarding to the project. Each doc follows the same shape: **what it is, why it
exists, how it works (briefly), key files, interfaces, status & limitations, and future &
scaling.** For the design rationale behind these choices, see
[03 — Architecture & ADRs](../03_Architecture_and_Decision_Records.md); for exact API/data
shapes, [04 — API & Data Contracts](../04_API_and_Data_Contracts.md).

**Status legend:** 🟢 Live on staging · 🔧 Dev-only tooling · 🟡 Partly built / in progress

---

## Conversation & content
*How a visitor gets a trustworthy answer.*

| Capability | In one line | Status | Since |
|---|---|---|---|
| [Public chat & the turn loop](chat-and-turn-loop.md) | The streaming visitor conversation — one atomic, stateless turn at a time. | 🟢 | POC/V1 |
| [Canonical answers & the approval lifecycle](canonical-answers.md) | Approved, must-win answers for sensitive topics, served through a draft→approved gate. | 🟢 | POC/V1 |
| [Knowledge retrieval (Vector Store)](knowledge-retrieval.md) | Managed retrieval over the approved knowledge corpus via an OpenAI Vector Store. | 🟢 | V1 |

## Requests & operations
*Turning intent into a delivered, tracked request — without the model in the write path.*

| Capability | In one line | Status | Since |
|---|---|---|---|
| [Requests & external delivery](request-delivery.md) | Persist a request locally, then deliver it asynchronously via a pluggable transport (mock by default). | 🟢 | V1 |
| [Background worker & durable jobs](worker-and-jobs.md) | A dedicated worker running Mongo-backed jobs — delivery, retention, analytics — with retries and dead-letter. | 🟢 | V1 |

## Admin & governance
*Team visibility and control, with privacy built in.*

| Capability | In one line | Status | Since |
|---|---|---|---|
| [Admin console: roles, masking & audit](admin-roles-and-audit.md) | Role-controlled admin with PII masked by default and every reveal audited. | 🟢 | V1 |
| [Admin knowledge management](admin-knowledge-mgmt.md) | Upload / approve / remove / replace knowledge sources against the real Vector Store. | 🟢 | V1 |
| [Privacy: retention & verified deletion](privacy-and-retention.md) | Job-driven retention and verified single-store deletion for subject requests. | 🟢 | V1 |

## Analytics & quality
*Understanding demand, and proving the bot behaves.*

| Capability | In one line | Status | Since |
|---|---|---|---|
| [Analytics & insights](analytics-and-insights.md) | Labeling, conversation insights, knowledge-gap ranking, funnel, and summaries — all worker-owned. | 🟢 | V1.5 |
| [Evaluation — the golden-set gate & dev tool](evaluation.md) | 37 golden cases through the real orchestrator; a release gate and a standalone dev tool. | 🔧 / gate | V1/V1.5 |

## Platform
*The ground the rest runs on.*

| Capability | In one line | Status | Since |
|---|---|---|---|
| [Configuration, prompts & environments](config-and-environments.md) | Central config, versioned prompts with a fallback model, and separate staging/production. | 🟢 | V1 |

---

### How to read this alongside the planning docs

- The **planning package** (docs `01`–`06`) describes what was *designed*. This catalog describes
  what was *built* and how it stands today — when they differ, the catalog reflects reality.
- Chronological decisions (with the "why") are in [DECISIONS_LOG.md](../DECISIONS_LOG.md);
  the durable architecture decisions are the ADRs in [doc 03](../03_Architecture_and_Decision_Records.md).
- Launch-readiness is tracked in the [V1 exit report](../V1_EXIT_REPORT.md) and
  [security review](../SECURITY_REVIEW_V1.md).
