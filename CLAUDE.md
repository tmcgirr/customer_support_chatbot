# CLAUDE.md — Cadre AI Support Chatbot (V1)

Public-facing customer support chatbot for Cadre AI (an AI strategy consultancy).
FastAPI backend + React chat widget (iframe) + MongoDB + OpenAI Responses API.

**V1 makes the shipped POC production-grade and operable for public use** — without
changing the model trust boundary (the model stays read-only; authenticated clients,
tenancy, and private stores remain V2). V1 adds: production-approved content with an
approval lifecycle, **external delivery of requests via a background worker**,
role-controlled admin with **audit**, **retention/deletion operations**, versioned
prompts/model with fallback, and **separate staging/production** environments.

Authoritative docs (`docs/`): V1 scope is `docs/02_Release_Capability_Plan.md` §4 and
the **P1** items in `docs/06_Backlog_and_Delivery_Plan.md`; the V1 exit bar is doc 02 §8
"V1 public gate". API/data contracts are `docs/04_API_and_Data_Contracts.md`;
architecture/ADRs `docs/03`; content + golden set `docs/05`. Execution phases: `plan.md`.
POC history: `docs/archive/{CLAUDE_POC,plan_POC}.md`, `docs/POC_EXIT_REPORT.md`,
`docs/DECISIONS_LOG.md`. Ongoing decisions with owners: doc 06 §6.

## Commands

```bash
# Backend (from backend/)
uv sync
uv run uvicorn app.main:app --reload --port 8000
uv run python -m app.worker           # V1: dedicated background worker (delivery/retention/aggregates)
uv run pytest                          # unit + integration tests
uv run pytest tests/integration/test_chat.py -x   # fastest signal on the core turn/stream path
uv run ruff check . && uv run ruff format --check .
uv run mypy app/

# Frontend (from frontend/)
pnpm install && pnpm dev               # widget (:5273) + admin (admin.html)
pnpm build && pnpm test

# Infra
docker compose up -d mongo             # local dev: MongoDB only (app + worker run via the commands above)
# docker compose --profile full up --build   # full dockerized stack

# Data / content scripts (from backend/)
uv run python scripts/seed_canonical.py       # canonical answers (draft → approve lifecycle in V1)
uv run python scripts/upload_knowledge.py     # push docs/knowledge/ to a Vector Store (staging or prod)
uv run python scripts/sweep_locks.py          # release leaked run locks (also a scheduled worker job in V1)

# Golden evaluation set — the release GATE. MUST pass on the TARGET config before a
# prompt/model/canonical/content change is promoted (staging → production).
uv run python -m eval.run                     # real model gate (spends API $)
uv run python -m eval.run --show              # + print each case's response text + routed intent
# Dev/test tool (standalone, outside the app — tester guide: docs/EVAL_TESTER_GUIDE.md):
uv run python -m eval.run --report r.html --pdf r.pdf   # shareable HTML + PDF report
uv run python -m eval.run --model M --prompt-version sys-v2   # one-off model/prompt A-B
uv run python -m eval.run --compare eval/configs.yaml --report r.html   # rank configs + diff
```

## Architecture invariants (do not violate)

These hold from the POC and remain load-bearing in V1:

1. **MongoDB is the single source of truth for conversation history.** Model calls are
   stateless: build the window from the conversation document and call the Responses API
   through `app/agent/adapter.py`. NEVER create or reference OpenAI Conversation objects.
2. **The model is read-only.** Its only tools are `search_knowledge`,
   `get_canonical_answer`, `get_portal_information`. NEVER register a tool that writes,
   sends, or submits anything. Side effects happen only via `POST /api/v1/requests`
   (browser, after user confirmation) and the delivery worker (invariant 11).
3. **One atomic turn operation.** Run lock + user-message append + duplicate check +
   message cap in a single `findOneAndUpdate` (docs 03 §3.1). A live turn heartbeats its
   lock; a leaked lock is swept. Never add a second lock mechanism or a messages collection.
4. **Provider isolation.** Model-provider types/IDs/errors (OpenAI **and** Anthropic) never
   leave `app/agent/adapter.py` — both `OpenAIResponsesAdapter` and `AnthropicMessagesAdapter`
   sit behind the one `ModelAdapter` protocol; which one is active is resolved outside
   (`app/agent/provider.py`) and switchable at runtime from admin. The SAME rule applies to
   every external system in V1: CRM/scheduler and ticketing SDKs, IDs, and errors never leave
   their adapter in `app/domain/delivery/`. Downstream sees normalized types only.
5. **No PII or message content in logs.** Structured events with IDs only. Applies to
   exceptions and to the worker/delivery paths. Event messages are static; a static AST
   scan + the runtime formatter guard enforce it (`tests/core/test_log_hygiene.py`).
6. **Public API returns local IDs only** (`cnv_`, `msg_`, `req_`… ULID via
   `app/core/ids.py`). Never expose OpenAI file/store IDs, external CRM/ticket IDs, or
   Mongo internals. External references are stored and shown ONLY in the audited admin.
7. **Idempotency everywhere writes happen:** `client_message_id` (messages),
   `Idempotency-Key` (requests, per conversation), and **idempotent delivery jobs** (an
   external system is called at most once per request; retries replay, never double-send).
8. **Canonical answers win.** Pricing, security/compliance, AI Maturity Index, portal,
   case studies, and client-relationship questions come from `canonical_answers`, never
   generated. In V1 canonical/content moves through a **draft → approved** lifecycle and is
   promoted from staging; only `approved` records are served. Unsupported questions escalate.
9. Session auth is a stateless HMAC token (`app/core/security.py`). No session collection.
10. Error responses use the fixed code list in contracts §6 — never raw exceptions or
    provider messages. Add codes to the enum.

**V1 additions (new trust-boundary rules):**

11. **External delivery is asynchronous and worker-owned.** A request is persisted locally
    first (unchanged), then a dedicated worker delivers it via `app/domain/delivery/` with
    **bounded retries → dead-letter**, storing the external reference and surfacing failures
    in admin. The model never delivers; the request handler never delivers inline. Ambiguous
    outcomes are resolved by the job, **never by re-prompting the user**.
12. **Admin is role-controlled: `admin` and `viewer`** (via the production identity
    provider). Masking is the default. **Every PII reveal/export, content, and deletion action
    writes an append-only audit record** (`app/domain/audit/`) with a non-empty `reason`. The
    reason is optional to *type* in the admin UI — a descriptive default is auto-recorded when
    left blank (DECISIONS_LOG 2026-07-09); the backend still requires a non-empty reason.
13. **Data lifecycle is job-driven and verified.** Retention classes/periods are enforced by
    scheduled worker jobs; deletion requests are verified, then execute single-store deletion
    plus documented provider-retention terms. No ad-hoc deletes on the request path.
14. **Staging and production are separate** (separate MongoDB, OpenAI project, and Vector
    Store). Approved content, prompts, and model config are **promoted**, never edited
    directly in production; the golden set gates every promotion.
15. **Prompts and model configuration are versioned.** Changing either requires the golden
    gate to pass on the target config; an approved fallback model is configured. The chat
    provider (OpenAI/Anthropic) is admin-switchable at runtime (persisted in `app_settings`,
    audited); gate the target provider first with `eval.run --provider <p>` — a switch is a
    promotion, not an ad-hoc edit.

## Code conventions

- Python 3.12, full type hints, Pydantic v2 for every API body, Mongo document, and job payload.
- Async throughout the request path (`motor`); no blocking calls in handlers or the worker loop.
- Routes → domain services → repositories. Routes NEVER touch Mongo directly. The worker uses
  the same repositories/services — no duplicated data access.
- Repo layout: today `backend/app/{api,core,domain,agent}`; V1 adds `app/jobs/` (worker +
  job model), `app/domain/{delivery,audit,retention}`, and the worker entrypoint
  `app/worker.py`. Also `backend/eval/`, `frontend/src/` (widget + `src/admin/`), `docs/`,
  `scripts/`. Job/privacy-request schemas + indexes are already specified in contracts §7–8.
- Tests mirror `app/`. Mock the model adapter at its boundary (`FakeAdapter`) and delivery
  adapters at theirs (`FakeDeliveryClient`) — never mock SDK internals, never call a real
  external API (model, CRM, ticketing) in tests. Delivery jobs get failure-path tests
  (retry, dead-letter, replay) — a V1 gate requirement.
- Frontend: React + TS + Vite. Widget runs in an iframe; host page communication only via
  origin-checked `postMessage`. Admin is a separate entry (`admin.html`). Never `localStorage`
  for anything sensitive; admin Basic-auth creds persist only in `sessionStorage` (per-tab,
  cleared on sign-out/tab close, re-verified via `/me` on load) — see DECISIONS_LOG 2026-07-09.
- Config only via `app/core/config.py` (pydantic-settings). Never read `os.environ`
  elsewhere. `ENV` defaults to `prod` (fail-closed); non-dev refuses default secrets.
- Conventional commits; one phase checkpoint per commit (see `plan.md`).

## Content rules (mirror the prompt, enforce in code review)

The bot must never state a fixed consulting fee/hourly rate/project total, certifications,
compliance/residency status, specific client or individual names, SLAs, or timelines; never
request credentials; never confirm whether someone is a client. It MAY state approved public
facts served via canonical/knowledge: the published pricing framing (the AI Transformation
Intensive; ~$30/employee/month for underlying AI *tool* licenses), the public eight-pillar
AI-Maturity framework (but no numeric scoring), the data-isolation assurance, and anonymized
outcomes (no names). See the 2026-07-09 content-refresh entry in `docs/DECISIONS_LOG.md`.
Covered by `eval/golden_set.yaml`. If you touch `app/agent/prompts/`, canonical seeds, or
approved content, run `python -m eval.run` on the target config and include the result.
`must_use_canonical` is a hard gate only for the mandatory-canonical topics (invariant 8);
general topics (company/service/industry) assert safety, not a specific route.

## Working style

- Follow `plan.md` phase by phase. At each ✅ CHECKPOINT: run the listed verification, fix
  failures, commit, then STOP and summarize before the next phase.
- **V1 has external dependencies.** Some phases block on decisions owned outside engineering
  (destinations, identity provider, legal/retention wording — doc 06 §6). Work unblocked
  phases; for a blocked one, build against the interface with a fake/placeholder and flag the
  decision. Content approval is a **parallel track from day one** (longer lead time than code).
- Every feature's definition of done includes: behavior per contract, safe errors, no
  PII/secrets in logs, config documented, **demonstrable on the deployed (staging) env**,
  golden set green where applicable, and failure paths tested for anything that delivers.
- When a decision isn't covered by the docs, choose the simplest option consistent with the
  invariants and note it in `docs/DECISIONS_LOG.md`.
- Prefer editing existing files over parallel versions. No `_v2` files.
- When debugging: reproduce with a failing test first, then fix, keep the test.
