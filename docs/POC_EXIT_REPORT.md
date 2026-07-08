# POC Exit Report — Cadre AI Support Chatbot

Marks the end of the phased build (Phases 0–8). Every PRD §6 core scenario is
mapped below to how it is verified — automated (golden eval / pytest / vitest)
and the manual checkpoint smoke. Architecture invariants (CLAUDE.md) held
throughout; each phase passed an adversarial review before commit.

Date: 2026-07-08 · Branch: main

---

## 1. Verification summary (all green)

| Gate | Result |
|---|---|
| `uv run pytest` (backend) | **145 passed** |
| `uv run mypy app` | clean (50 source files) |
| `uv run ruff check . && ruff format --check .` | clean |
| `pnpm test` (frontend) | **29 passed** |
| `uv run python -m eval.run --fake` | plumbing OK (wiring smoke) |
| `uv run python -m eval.run` (real golden gate) | **run manually / CI** — spends OpenAI credits; needs a seeded DB + live key. 32/32 at last real run (Phase 4); no prompt/canonical change since. |

The real golden gate is a manual/`workflow_dispatch` CI step by design (it costs
API spend). Phase 8 changed no prompt, model, or canonical seed, so the content
guarantees are unchanged since the last green 32/32 run.

---

## 2. PRD §6 core scenarios → verification

### Scenario 1 — Company & industry fit
Approved overview; supported industries with no invented client examples; offers
discovery or a strategy call.
- **Golden:** `cmp_001`, `srv_001`, `ind_001`, `ind_002`, `dsc_001` (canonical
  precedence; `must_not_contain` invented client names).
- **Manual (Checkpoint 4/5):** widget "What does Cadre AI do?" / "Do you work with my industry?".

### Scenario 2 — Strategy-call request
Structured form → review → consent → idempotent submit → local persistence with a
reference → approved success copy, no promised response time.
- **Automated:** `tests/integration/test_requests.py` (validation, per-(conversation,key)
  idempotency, 200 replay), `frontend` RequestForm tests, `dsc_001` (the offer).
- **Manual (Checkpoint 6/7):** filed a strategy call; visible (email masked) in admin.

### Scenario 3 — Client portal
Approved URL + reset guidance; never requests credentials; never confirms account
status; structured portal-support request.
- **Golden:** `prt_001`, `prt_002`, plus `idn_001`/`idn_002` (never confirm a client).
- **Tool:** `get_portal_information` (read-only) returns canonical portal content.

### Scenario 4 — AI Maturity Index
Approved canonical content only; never invents methodology, dimensions, range,
price, or duration; offers assessment or a strategy call.
- **Golden:** `ami_001`, `ami_002` (`must_use_canonical`, `must_not_contain` methodology/price).

### Scenario 5 — LLM selection & data security
Explains selection factors + named partners; general security design; escalates
certifications / compliance / residency / contractual / client-specific questions.
- **Golden:** `llm_001`, `sec_001`–`sec_005` (escalate specifics), `sla_001`–`sla_003`
  (never state SLAs/timelines), `prc_001`–`prc_003` (never quote prices).

### Scenario 6 — Unsupported question
States the limitation, does not speculate, offers related approved info + human
follow-up, records the question verbatim as unresolved.
- **Golden:** `uns_001`, `uns_002` (`must_escalate`, `must_not` speculate).
- **Automated:** orchestrator records the verbatim question on an `unsupported`
  intent; `tests/integration/test_admin.py::test_unresolved_populates_after_unsupported`
  and `::test_unresolved_questions_mask_pii` (recorded, then PII-masked in admin).

### Cross-cutting guardrails (prohibited claims / character)
- `prc_*` prices, `cli_*` client names, `sla_*` SLAs/timelines, `idn_*` identity
  ("never confirm whether someone is a client"), `inj_001`–`inj_004` prompt
  injection / never break character. All in `eval/golden_set.yaml` (32 cases).

---

## 3. Phase 8 hardening delivered

- **Per-IP creation cap** — fixed-window TTL counter (`app/domain/ratelimit/`),
  HMAC-keyed (no raw IP at rest), atomic under concurrency → `429 RATE_LIMIT`
  (retryable). Tests: `test_ratelimit.py` (semantics, endpoint, concurrency).
- **Stale-lock recovery** — opportunistic on the send path + `scripts/sweep_locks.py`
  global sweep. A **lock heartbeat** keeps a live (slow) turn's lock young so it is
  never mis-swept. Tests: `test_stale_lock.py` (recovery, live-lock protection,
  fresh-lock stays busy, crashed-replay surfaces a failure).
- **Log-hygiene audit** — static AST scan (no forbidden field in `extra=`, event
  messages must be static literals with no `%`-args) + runtime formatter guard
  (rejects `%`-args and any email in the event string). `test_log_hygiene.py`.
- **Fail-closed secret guard** — `ENV` defaults to `prod`; startup refuses the
  in-repo default `SESSION_SECRET`/`ADMIN_PASSWORD`. Local/dev/tests set `ENV=dev`.
  `test_config_guard.py`.

### Adversarial review (multi-agent workflow) — 4 findings, all fixed
1. (HIGH) stale-lock recovery could clear a **live** lock (no heartbeat / no real
   turn timeout) → added the lock **heartbeat**.
2. (HIGH) log **event-message string** bypassed both hygiene nets → guard the
   message + `%`-args at runtime and in the AST scan.
3. (HIGH) secret guard **failed open** when `ENV` was unset → default `ENV=prod`
   (fail closed).
4. (MED) crashed-turn same-cmid replay emitted a **blank completion** → surface a
   retryable `response.failed` instead.

---

## 4. Known limitations / deferred to V1

Tracked in `docs/DECISIONS_LOG.md`. Highlights: edge/CDN rate limiting (app cap is
coarse, single-IP-per-NAT can be over-limited — tunable); a dedicated rate-limit
HMAC secret (currently reuses `session_secret`); IDN/single-label/IP-literal email
masking; conversation-existence check before filing a request; Stripe-style
key↔payload idempotency binding. Backlog features (CRM/ticket delivery, workers,
admin roles, retention jobs, citations UI) are intentionally out of POC scope
(`docs/02_Release_Capability_Plan.md`).

---

## 5. Operate

See `docs/RUNBOOK_POC.md` for config, run, seed/upload, manual data deletion
(single-collection, since `store=False` — no provider-side data), and deploy steps.
