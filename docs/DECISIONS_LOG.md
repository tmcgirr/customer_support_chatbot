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
