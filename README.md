# Cadre AI — Customer Support Chatbot

A public-facing customer-support chatbot for **Cadre AI**, an AI strategy & implementation
consultancy. Visitors ask about services, approach, security, and pricing in a chat widget;
the bot answers from approved content, and — only after the visitor confirms — hands off
structured requests (a strategy call, portal support, or an escalation) to the business.

**Stack:** FastAPI backend + a React chat widget (iframe) and admin SPA + MongoDB +
the OpenAI Responses API and Vector Stores.

> **New here? Start with the [Capabilities Catalog](docs/capabilities/) — one short doc per
> feature (what it is, why it exists, status, and where it can go). This README is the map;
> the catalog is the tour.**

---

## Current status

| | |
|---|---|
| **Build** | **V1** (production-grade POC) + a **V1.5** feature wave — both complete |
| **Running on** | a **staging** environment (DigitalOcean droplet + DO Managed MongoDB), with **mock** request delivery |
| **Tests** | 384 backend · 56 frontend, green |
| **Production** | **not yet stood up** — gated on content sign-off, a real delivery destination, retention/legal sign-off, and infra (a domain, CDN/WAF, a pager). *These are owner/infra decisions, not remaining engineering.* |

What actually shipped, feature by feature, is in the **[Capabilities Catalog](docs/capabilities/)**.

---

## What it is

- A **public chat widget** (embedded in an iframe) that streams answers token-by-token.
- Answers come from **approved content only**: a small **canonical-answer** set wins for
  sensitive topics (pricing, security, portal, case studies), and an **OpenAI Vector Store**
  provides retrieval over an approved knowledge corpus.
- The **model is read-only** — its only tools *look things up*. It never writes, sends, or
  submits. Every side effect (a strategy-call request, an escalation) happens through a typed
  application endpoint **after the visitor confirms**, and is delivered asynchronously by a
  background worker.
- An **admin console** (role-controlled, PII-masked, audited) gives the team visibility:
  conversations, requests, knowledge management, analytics/insights, and privacy operations.

## Architecture at a glance

- **FastAPI modular monolith** + a dedicated **background worker** — no Redis/broker; jobs live in MongoDB.
- **MongoDB is the single source of truth** for conversation history. Model calls are stateless:
  each turn rebuilds a windowed transcript from the conversation document and calls the Responses API.
- **Provider isolation** — OpenAI (and any CRM/ticketing) types, IDs, and errors never leave their adapter.
- **React** (Vite + TS): a widget (`iframe`, `postMessage` to the host) and a separate admin entry.
- **Two environments** — staging and production are fully separate (Mongo, OpenAI project, Vector Store);
  approved content, prompts, and model config are **promoted**, gated by a golden evaluation set.

The load-bearing design rules are the **architecture invariants** in [CLAUDE.md](CLAUDE.md);
the full rationale is in [docs/03 — Architecture & Decision Records](docs/03_Architecture_and_Decision_Records.md).

---

## Repository map

```
backend/            FastAPI app + worker + evaluation harness + tests
  app/
    api/            HTTP layer — public/ (widget), admin/ (console), deps, sse
    agent/          model orchestration — orchestrator, adapter, tools, prompts/
    core/           config, ids, security, masking, logging, errors
    domain/         one package per capability (canonical, knowledge, requests,
                    delivery, jobs, audit, privacy, analytics, insights, …)
    worker.py       the background worker entrypoint
  eval/             standalone golden-set evaluation tool (dev-only)
  scripts/          seed canonical answers, upload knowledge, sweep locks
frontend/           React — chat widget + admin SPA (Vite + TS)
  src/              conversation/, shell/, host/, forms/ (widget) · admin/ · api/
deploy/             docker-compose (staging/prod), Caddy, env examples
scripts/            Mongo backup / restore
docs/               planning package, capabilities catalog, runbooks, knowledge corpus
```

---

## Getting started (local)

```bash
docker compose up -d mongo            # local MongoDB only

# Backend (from backend/)
uv sync
uv run uvicorn app.main:app --reload --port 8000   # API
uv run python -m app.worker                        # background worker
uv run pytest                                      # tests

# Frontend (from frontend/)
pnpm install && pnpm dev              # widget (:5273) + admin (admin.html)
```

Fuller setup, seeding, and ops are in [QUICKSTART.md](QUICKSTART.md) and the
[runbooks](docs/RUNBOOK_PROD.md). Configuration is centralized in `backend/app/core/config.py`
(pydantic-settings) — see [Configuration, prompts & environments](docs/capabilities/config-and-environments.md).

---

## Documentation map

**Start here (the shipped system):**
- **[Capabilities Catalog](docs/capabilities/)** — one doc per feature: what / why / status / future.
- [CLAUDE.md](CLAUDE.md) — the architecture invariants (the trust boundary), for anyone changing code.

**Planning package (the design):**
- [01 — Product Requirements](docs/01_Product_Requirements_Document.md) ·
  [02 — Release & Capability Plan](docs/02_Release_Capability_Plan.md) ·
  [03 — Architecture & ADRs](docs/03_Architecture_and_Decision_Records.md) ·
  [04 — API & Data Contracts](docs/04_API_and_Data_Contracts.md) ·
  [05 — Conversation & Content Spec](docs/05_Conversation_and_Content_Specification.md) ·
  [06 — Backlog & Delivery Plan](docs/06_Backlog_and_Delivery_Plan.md)

**Operations & compliance:**
- [Staging deploy](docs/DEPLOY_STAGING.md) · [Production deploy](docs/DEPLOY_PROD.md) ·
  [Production runbook](docs/RUNBOOK_PROD.md) · [Privacy notice (DRAFT)](docs/PRIVACY_NOTICE.md) ·
  [Security review (V1)](docs/SECURITY_REVIEW_V1.md)

**Quality:**
- [Evaluation tester guide](docs/EVAL_TESTER_GUIDE.md) — the golden-set gate + dev tool.

**History & decisions:**
- [V1 exit report](docs/V1_EXIT_REPORT.md) · [POC exit report](docs/POC_EXIT_REPORT.md) ·
  [Decisions log](docs/DECISIONS_LOG.md) · [archive/](docs/archive/) (POC-era guides).

---

## The trust boundary (quick reference)

These hold everywhere and are enforced in code review (full list in [CLAUDE.md](CLAUDE.md)):

1. **MongoDB is the single source of truth** for conversation history; model calls are stateless.
2. **The model is read-only** — tools only look things up; side effects go through typed endpoints after user confirmation, delivered by the worker.
3. **Provider isolation** — external types/IDs/errors never leave their adapter; the public API returns local IDs only.
4. **Canonical answers win** for sensitive topics; only *approved* content serves.
5. **No PII or message content in logs;** admin masks PII by default and audits every reveal.
