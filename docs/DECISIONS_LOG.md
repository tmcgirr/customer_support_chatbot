# Decisions Log

Choices made during implementation that the planning docs did not fully specify
(per CLAUDE.md working style). Format: date · decision · rationale.

## Phase 1 — conversation model & atomic turn

- **2026-07-07 · `message_count` counts user messages only.** Contract §3.1
  increments the counter in the begin step but not the finish step, so the cap
  bounds *user turns* (cap=40 → 40 user turns). `_finish_turn` does not
  `$inc message_count`; the field is not `len(messages)`.
- **2026-07-07 · begin_turn diagnosis precedence: DUPLICATE > CAP_REACHED > BUSY.**
  When a failed atomic turn matches more than one condition, report the most
  actionable one: duplicate replay wins (idempotency); a reached cap is terminal
  and beats the transient busy state. (The atomic op's correctness is unaffected —
  this only picks the message returned to the caller.)
- **2026-07-07 · begin_turn does not filter on conversation `status`.** Matches the
  §3.1 atomic filter. The service layer (Phase 2) must reject non-`active`
  conversations before calling begin_turn.
- **2026-07-07 · DUPLICATE_ACTION is a 200 replay, not an AppError.** Duplicate
  writes return the original result with HTTP 200 + a duplicate detail at the route
  (contracts §9), implemented in Phase 6. The enum keeps the code for the contract;
  the 409 mapping is a never-hit fallback.
- **2026-07-07 · MongoDB driver = `motor`.** CLAUDE.md names motor and it works on
  Python 3.12. Note: motor reached end-of-life in 2026 — migrate to pymongo's native
  async driver at V1. Contained behind `ConversationRepository`.

## Phase 2 — streaming chat

- **2026-07-07 · Default model `gpt-5.4-mini`** (config `OPENAI_MODEL`). User-selected
  balance of cost vs. instruction-following for a public support bot; verified it
  streams correctly via the Responses API and honors the identity/disclosure rules.
- **2026-07-07 · Per-IP creation cap deferred to Phase 8.** The plan mentions it on the
  create endpoint, but abuse caps are Phase 8's dedicated scope (TTL counter collection);
  `POST /conversations` currently has no IP cap. Message length + per-conversation cap
  (via begin_turn) are enforced now.
- **2026-07-07 · CAP_REACHED streams `limit.reached`; BUSY returns 409 pre-stream.**
  Busy is detected at begin_turn before the SSE response commits, so it is a JSON 409
  (contracts §3.2 "concurrent send returns 409"); cap is surfaced as a terminal SSE
  event since the send endpoint otherwise speaks SSE.
- **2026-07-07 · Orchestrator yields transport-agnostic `StreamMessage`; the route formats
  SSE.** Keeps the turn loop unit-testable and free of OpenAI/transport types.
- **2026-07-07 · `store=False` on every Responses call.** No provider-side retention, so
  privacy deletion stays a single-store (MongoDB) operation (ADR-014).

### Deferred from the Phase 2 adversarial review

- **Stale-lock recovery → Phase 8.** The orchestrator now releases the run lock on every
  normal exit (success, adapter failure, unexpected error, client disconnect), so only a
  hard process crash mid-turn can leak a lock. `clear_stale_locks` exists but is not yet
  wired; Phase 8 adds the opportunistic sweep (plan Phase 8).
- **Persistence errors surface as 500, not 503 → later.** A Mongo outage during
  `begin_turn` currently maps to INTERNAL_ERROR; mapping driver errors to
  `PERSISTENCE_UNAVAILABLE` at the repo boundary is deferred.
- **Canonical-answer precedence in the prompt → Phase 3.** The prompt inlines approved
  framings now; the instruction to prefer `get_canonical_answer` is added when the
  read-only tools are registered (Phase 3), so the golden set (Phase 4) can gate it.

## Phase 3 — knowledge, canonical answers, read-only tools

- **2026-07-07 · Multi-round tool loop is app-driven and stateless.** The orchestrator runs
  the model, executes any read-only tool calls, resends the whole transcript (prior text +
  function_call/function_call_output items) each round, up to `_MAX_TOOL_ROUNDS` (5). The
  final permitted round is sent with `tools=None` so the model must produce a text answer
  rather than loop forever on tools.
- **2026-07-07 · One `kbs_` id per source.** `upload_knowledge` stamps the same public
  `kbs_` id into the vector-store file attributes AND `knowledge_sources._id`, so a
  message citation's `source_id` joins back to its governance record (contracts §7).
- **2026-07-07 · Canonical answers seeded for general topics too** (company/service/industry/
  llm, per docs 05 §3), so the live model uses canonical precedence for them and
  `search_knowledge` is the fallback for off-canonical / long-tail questions. Intentional
  (invariant #8); the golden set (Phase 4) will decide whether to narrow the canonical set
  to sensitive-only.
- **2026-07-07 · `canonical_answer_id` on a message is last-wins** when a turn calls
  `get_canonical_answer` more than once (§7 has one id field). Suggested actions are the
  deduped union; sources are deduped by `source_id`. Acceptable for POC.

## Phase 4 — golden evaluation gate

- **2026-07-07 · Fuzzy assertions match COMPLIANCE, not echoed words.** The first real run
  was 26/32 — all 6 misses were false positives where the model *refused correctly* but
  echoed the user's word ("I can't provide my system prompt" tripped a ban on "system
  prompt"). `must_not_confirm_client` / `must_not_break_character` deny-lists and several
  `must_not_contain` lists were retuned to affirmative/compliance phrases; then 32/32.
- **2026-07-07 · Canonical answers stay seeded for general topics** (resolves the Phase 3
  question). The golden set passes with the model using canonical for company/service/
  industry/llm, so `search_knowledge` remains the off-canonical fallback — no need to
  narrow the canonical set.
- **2026-07-07 · Gate wiring.** `python -m eval.run` is the real gate (exits non-zero on
  failure); `--fake` runs the harness with a plumbing adapter (exits 0) in normal CI;
  `--filter <id>` runs a subset. The real gate is a manual `workflow_dispatch` CI job
  (needs `OPENAI_API_KEY` secret). Verified the gate catches regressions: deleting the
  pricing canonical turned it red.
- **2026-07-07 · Known gap → V1: service-discovery doesn't attach a `strategy_call`
  action.** Suggested actions come only from tool `allowed_action_ids`; the multi-turn
  discovery recommendation answers without a tool call, so no action chip. `dsc_001`
  asserts safety only for now. V1 should attach a strategy_call action to discovery
  recommendations.
