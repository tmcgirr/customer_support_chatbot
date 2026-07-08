# CLAUDE.md — Cadre AI Support Chatbot

Public-facing customer support chatbot for Cadre AI (an AI strategy consultancy).
FastAPI backend + React chat widget (iframe) + MongoDB + OpenAI Responses API.
Full design docs live in `docs/` — the API/data contracts are in
`docs/04_API_and_Data_Contracts.md` and are authoritative. Execution phases are in `plan.md`.

## Commands

```bash
# Backend (from backend/)
uv sync                          # install deps
uv run uvicorn app.main:app --reload --port 8000
uv run pytest                    # unit + integration tests
uv run pytest tests/test_turn_loop.py -x   # fastest signal on the core path
uv run ruff check . && uv run ruff format --check .
uv run mypy app/

# Frontend (from frontend/)
pnpm install && pnpm dev         # widget dev server (port 5273)
pnpm build && pnpm test

# Infra
docker compose up -d mongo       # local dev: MongoDB only (app runs via uvicorn/pnpm above)
# docker compose --profile full up --build   # full dockerized stack; api on :8080 (deploy shape)
uv run python scripts/seed_canonical.py     # seed canonical answers
uv run python scripts/upload_knowledge.py   # push docs/knowledge/ to Vector Store

# Golden evaluation set — MUST pass before any prompt/model/canonical change is committed
uv run python -m eval.run        # runs eval/golden_set.yaml against the orchestrator
```

## Architecture invariants (do not violate)

1. **MongoDB is the single source of truth for conversation history.** Model calls are
   stateless: build the window from the conversation document and call the Responses API
   through `app/agent/adapter.py`. NEVER create or reference OpenAI Conversation objects.
2. **The model is read-only.** Its only tools are `search_knowledge`,
   `get_canonical_answer`, `get_portal_information`. NEVER register a tool that writes,
   sends, or submits anything. Side effects happen only via `POST /api/v1/requests`,
   called by the browser after user confirmation.
3. **One atomic turn operation.** Run lock + user-message append + duplicate check +
   message cap are enforced in a single `findOneAndUpdate` on the conversation document
   (see `docs/03_Architecture_and_Decision_Records.md` §3.1). Never add a second lock
   mechanism or a separate messages collection.
4. **Provider isolation.** OpenAI types, IDs, and errors never leave `app/agent/adapter.py`.
   Everything downstream sees normalized `StreamEvent`, `Usage`, `AdapterError`.
5. **No PII or message content in logs.** Log structured events with IDs only
   (`conversation_id`, `request_id`, `error_code`). Never log message text, emails,
   tool payloads, or tokens. This applies to exceptions too — sanitize before raising.
6. **Public API returns local IDs only** (`cnv_`, `msg_`, `req_`…, ULID-based via
   `app/core/ids.py`). Never expose OpenAI file/store IDs or Mongo internals.
7. **Idempotency everywhere writes happen:** `client_message_id` for messages,
   `Idempotency-Key` for requests. Duplicates replay the original result, never error blindly.
8. **Canonical answers win.** Pricing, security/compliance, AI Maturity Index, portal,
   case studies, and client-relationship questions must come from `canonical_answers`,
   never generated. Unsupported questions escalate — the bot never guesses.
9. Session auth is a stateless HMAC token (`app/core/security.py`). No session collection.
10. Error responses use the fixed code list in contracts §6. Add codes to the enum;
    never return raw exceptions or provider messages to clients.

## Code conventions

- Python 3.12, full type hints, Pydantic v2 models for every API body and Mongo document.
- Async throughout the request path (`motor`/async driver); no blocking calls in handlers.
- Routes → domain services → repositories. Routes NEVER touch Mongo directly.
- Repo layout: `backend/app/{api,core,domain,agent,jobs}`, `backend/eval/`,
  `frontend/src/`, `docs/`, `scripts/`.
- Tests mirror `app/` structure. Mock the adapter at its boundary (`FakeAdapter` in
  `tests/fakes.py`) — never mock OpenAI's SDK internals, never call the real API in tests.
- Frontend: React + TypeScript + Vite. The widget must run inside an iframe; communicate
  with the host page only via origin-checked `postMessage`. No localStorage for anything
  sensitive; drafts live in component state.
- Config only via `app/core/config.py` (pydantic-settings). Never read `os.environ` elsewhere.
- Conventional commits; one phase checkpoint per commit (see plan.md).

## Content rules (mirror the prompt, enforce in code review)

The bot must never state prices, certifications, client names, SLAs, timelines, or
AI Maturity methodology; never request credentials; never confirm whether someone is a
client. These are covered by `eval/golden_set.yaml` — if you touch
`app/agent/prompts/` or canonical seeds, run `python -m eval.run` and include the
result in your summary.

## Working style

- Follow `plan.md` phase by phase. At each ✅ CHECKPOINT: run the listed verification,
  fix failures, commit, then STOP and summarize before starting the next phase.
- When a decision isn't covered by the docs, choose the simplest option consistent with
  the invariants above and note it in `docs/DECISIONS_LOG.md`.
- Prefer editing existing files over creating parallel versions. No `_v2` files.
- When debugging: reproduce with a failing test first, then fix, keep the test.
