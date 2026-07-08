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
