# plan.md — Cadre AI Support Chatbot (POC build)

Execute phases **in order**. Each phase ends with a ✅ CHECKPOINT: run the verification,
fix anything red, commit with the listed message, then stop and summarize before
continuing. Phases marked ⚡ contain tasks safe to parallelize with subagents because
they touch disjoint files against already-frozen contracts.

Authoritative references: `docs/04_API_and_Data_Contracts.md` (schemas, endpoints,
errors), `docs/03_Architecture_and_Decision_Records.md` §3.1 (turn loop),
`docs/05_Conversation_and_Content_Specification.md` (content + golden set).

---

## Phase 0 — Scaffold and walking skeleton

Goal: prove the full pipe (browser → FastAPI → SSE stream → browser) with real
infrastructure shape before writing features. Deployment risk dies here, not in Phase 8.

1. Create repo layout per CLAUDE.md: `backend/` (uv project, FastAPI, ruff, mypy,
   pytest config), `frontend/` (Vite + React + TS), `docker-compose.yml` (mongo:7),
   `scripts/`, `eval/`, `.github/workflows/ci.yml` (lint, typecheck, test, build).
2. `GET /healthz` returning `{status, version}`; structured JSON logging with request
   IDs (`app/core/logging.py`) — verify no message-content fields exist in the log model.
3. `GET /api/v1/dev/stream-test`: SSE endpoint emitting 10 timed `response.delta`
   events then `response.completed`.
4. Frontend shell: a page that opens an EventSource against the stream test and renders
   deltas progressively.
5. Dockerfile for the backend; compose runs api + mongo together.

✅ CHECKPOINT 0 — `docker compose up` then observe deltas rendering one-by-one in the
browser (not buffered into one paint); `uv run pytest` and CI green.
Commit: `chore: walking skeleton with verified SSE`
> Deploy note (human task): push this skeleton to DigitalOcean and re-verify SSE through
> the real routing path before Phase 5. If deltas arrive buffered, fix proxy config now.

---

## Phase 1 — Core + conversation document model

Goal: the atomic turn primitive everything else sits on.

1. `app/core/`: `config.py` (pydantic-settings: MONGO_URI, OPENAI_API_KEY,
   SESSION_SECRET(S), MESSAGE_CAP=40, MESSAGE_MAX_CHARS=2000, IP_CREATE_CAP),
   `ids.py` (ULID with prefixes), `security.py` (HMAC token mint/verify with key IDs),
   `errors.py` (error enum + exception → error-contract handler).
2. Pydantic models for the `conversations` document exactly per contracts §7
   (embedded messages, `active_run`, `message_count`, `unsupported_questions`).
3. `ConversationRepository`:
   - `create()`,
   - `begin_turn(cid, user_msg, cmid)` → the single `findOneAndUpdate` implementing
     lock + append + dedupe + cap (ADR §3.1); returns one of
     `STARTED | DUPLICATE(existing) | BUSY | CAP_REACHED`,
   - `complete_turn(cid, assistant_msg)` (push + clear lock + touch activity),
   - `fail_turn(...)`, `clear_stale_locks(older_than)`,
   - `get_transcript(cid)`.
4. Indexes from contracts §8 created on startup (idempotent).
5. Tests against real Mongo (compose service): concurrency test — two simultaneous
   `begin_turn` calls, exactly one STARTED; duplicate cmid returns DUPLICATE; cap test;
   stale-lock recovery test.

✅ CHECKPOINT 1 — `uv run pytest tests/domain/ -x` green including the concurrency test;
mypy clean. Commit: `feat: conversation document model with atomic turn operations`

---

## Phase 2 — Adapter, orchestrator, chat endpoints

Goal: streamed multi-turn chat with a mockable model boundary.

1. `app/agent/adapter.py`: `send(messages, tools) -> AsyncIterator[StreamEvent]` over
   the OpenAI Responses API; normalize deltas, tool calls, usage, errors
   (`MODEL_UNAVAILABLE` mapping). Nothing OpenAI-typed escapes this file.
2. `tests/fakes.py`: `FakeAdapter` (scripted deltas/tool-calls/errors) — used by every
   test above this layer.
3. `app/agent/prompts/sys-v1.md`: versioned system prompt implementing identity, tone,
   answer pattern, prohibited claims, and escalation rules from docs 05 §1/§7.
4. `orchestrator.py` turn loop: begin_turn → build window (system + all messages;
   cap guarantees fit) → adapter.send with tool loop → SSE relay → complete/fail_turn,
   storing usage/latency/sources/error_code on the assistant message.
5. Public endpoints: `POST /api/v1/conversations` (welcome + suggested actions +
   token; per-IP cap), `POST /api/v1/conversations/{id}/messages` (SSE, full event
   sequence per contracts §3.2, BUSY/CAP/length handling), `GET .../messages`.
6. Integration tests with FakeAdapter: happy stream, duplicate replay, busy 409,
   cap → `limit.reached`, adapter failure → `response.failed` + failed message stored.

✅ CHECKPOINT 2 — full test suite green; manual smoke: `scripts/chat_repl.py` holds a
3-turn conversation against the dev server with the real API key.
Commit: `feat: streaming chat with stateless model calls`

---

## Phase 3 — Knowledge, canonical answers, tools ⚡

Goal: grounded answers with canonical precedence. Contracts are frozen, so run 3A/3B/3C
as parallel subagents, then integrate.

- **3A (subagent):** `knowledge/` — `scripts/upload_knowledge.py` (create Vector Store,
  upload `docs/knowledge/*.md`, record metadata in `knowledge_sources`), search adapter
  calling Vector Store search with `audience=public` forced app-side, result
  normalization, `RETRIEVAL_UNAVAILABLE` fallback. Unit tests with mocked provider.
- **3B (subagent):** `canonical/` — repository, `scripts/seed_canonical.py` seeding all
  records from docs 05 §3 (pricing, security, AI Maturity, portal, company, services,
  industries, partners, case-study policy, unsupported), `get_canonical_answer` matching
  by intent with `mandatory_escalation` honored. Tests.
- **3C (subagent):** `docs/knowledge/` corpus — author 10–15 markdown source files from
  docs 05 content (company, each service, industries, LLM selection/partners, security,
  engagement approach, maturity index). Content only; no code.
- **Integrate (main session):** register the three read-only tools with the
  orchestrator's tool loop; store `canonical_answer_id`/`sources` on messages; wire
  suggested-action IDs from canonical `allowed_action_ids`.

✅ CHECKPOINT 3 — tests green; REPL smoke: "what do you charge?" uses the pricing
canonical and offers strategy_call; "do you work with construction?" answers from
retrieval with stored sources; nonsense question triggers the unsupported pattern.
Commit: `feat: retrieval and canonical answers with read-only tools`

---

## Phase 4 — Golden evaluation harness

Goal: the regression gate, before the UI exists.

1. `eval/run.py`: loads `eval/golden_set.yaml`, drives the orchestrator (real adapter by
   default, `--fake` for CI plumbing tests), evaluates assertions
   (`must_use_canonical`, `must_not_contain`, `must_offer_action`, `must_escalate`,
   `must_not_confirm_client`, `must_not_break_character`), prints a per-case report,
   exits non-zero on failure.
2. Author the initial 30+ cases per docs 05 §8: six scenarios, pricing/cert/client/SLA
   probes, escalation triggers, unsupported, multi-turn discovery, injection probes
   (user-text and a poisoned test knowledge doc), credential refusal, AI disclosure.
3. CI job (manual-trigger + on changes to `prompts/`, canonical seeds, or `eval/`).

✅ CHECKPOINT 4 — `uv run python -m eval.run` green; deliberately break the prompt
(remove the pricing rule), confirm the gate fails, restore.
Commit: `feat: golden evaluation set and runner`

---

## Phase 5 — Chat widget UI ⚡

Goal: the iframe widget. Backend contracts frozen since Phase 2, so UI subtasks
parallelize; also parallel-safe with Phase 6 backend work.

- **5A (subagent):** widget shell — iframe app + host loader script with origin-checked
  postMessage (open/close/resize), launcher, header ("Cadre AI Assistant · AI"), privacy
  disclosure, welcome + suggested prompt chips, mobile layout.
- **5B (subagent):** conversation view — composer (client_message_id generation, length
  limit, disabled-while-busy), streaming renderer, suggested-action buttons, feedback
  control, error/partial/cap states with exact copy from docs 05 §6.
- **5C (subagent):** form panels — strategy-call, portal-support, escalation forms with
  client-side drafts, validation, review + consent + confirm step, success/failure/
  duplicate states. (Submits against the Phase 6 endpoint; stub the client until then.)
- Integrate; component tests (Vitest + Testing Library) for streaming render, busy
  lockout, and form review flow.

✅ CHECKPOINT 5 — `pnpm test` green; manual: full conversation with streaming, an action
chip opening a form, error state on server kill.
Commit: `feat: iframe chat widget`

---

## Phase 6 — Requests endpoint

Goal: the one write path.

1. `POST /api/v1/requests`: per-type Pydantic schemas (contracts §3.4), email
   validation, `confirmed` + `consent_version` required, unique idempotency key →
   replay with `DUPLICATE_ACTION` detail, reference generation (`REQ-XXXX`),
   escalation type stores verbatim question + safe summary; escalation contact optional.
2. `POST /api/v1/messages/{id}/feedback` with ownership check.
3. Record `outcome` on the conversation when a request is created.
4. Wire the widget forms to the live endpoint; verify preserved-draft-on-failure.
5. Tests: each type, validation failures, idempotent replay, feedback ownership.

✅ CHECKPOINT 6 — suite green; manual: submit each request type end-to-end from the
widget, see the reference, resubmit and get the duplicate message.
Commit: `feat: unified requests with idempotent submission`

---

## Phase 7 — Read-only admin ⚡

Goal: operational visibility. 7A/7B parallelize (API vs UI once API schemas are written first).

- **7A:** admin router behind basic auth (config credentials, HTTPS assumption
  documented): dashboard metrics, conversation list + detail (masked email everywhere:
  `a***@acme.com`), requests list with type/status filters, unresolved-questions list
  (from `unsupported_questions`).
- **7B (subagent):** minimal admin UI (separate route/app, desktop-first) rendering the
  five views. Plain tables; no design system needed.
- Tests: masking helper (property-style over odd emails), auth required on every admin
  route, unresolved list populates after an unsupported question.

✅ CHECKPOINT 7 — suite green; manual: hold a chat with one unsupported question and one
strategy-call request, confirm all of it is visible (masked) in admin.
Commit: `feat: read-only admin dashboard`

---

## Phase 8 — Hardening and POC exit

1. Abuse caps verified end-to-end: message length, per-conversation cap UX, per-IP
   creation cap (TTL counter collection).
2. Log-hygiene audit: grep-based test asserting no `content`, `email`, `body` fields in
   any log call; exception paths sanitized.
3. Stale-lock sweep wired (opportunistic on request + `scripts/sweep_locks.py`).
4. `docs/RUNBOOK_POC.md`: env vars, seed/upload scripts, manual deletion procedure
   (single collection), deploy steps.
5. Full pass: `pytest`, `mypy`, `ruff`, `pnpm test`, `python -m eval.run`, and the six
   scenario walkthroughs from `docs/01_Product_Requirements_Document.md` §6.

✅ CHECKPOINT 8 (POC exit) — everything above green; write `docs/POC_EXIT_REPORT.md`
mapping each PRD scenario to how it was verified.
Commit: `chore: POC hardening and exit checklist`

---

## Backlog (do NOT build during POC phases)

CRM/ticket delivery jobs, dedicated worker, admin roles/identity provider, knowledge
management UI, retention jobs, reconnect UX, citations UI, intent/topic labeling,
conversation summaries. See `docs/02_Release_Capability_Plan.md` for V1.
