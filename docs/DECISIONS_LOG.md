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

## Phase 5 — iframe chat widget

- **2026-07-07 · Streaming uses fetch + a stream reader, not EventSource** (the send-message
  endpoint is POST-with-SSE). The parser normalizes CRLF, flushes a trailing frame, and —
  if the stream closes with no terminal event (proxy/LB drop) — the turn is marked failed
  with the partial text kept and a retry offered (never a permanent "streaming" hang).
- **2026-07-07 · Session token lives in memory only** (never localStorage); sent as
  `Authorization: Bearer`; never posted to the host or logged. Host↔iframe messaging is
  origin-checked (`src/host/messaging.ts`); `public/loader.js` embeds the iframe.
- **2026-07-07 · One idempotency key per form submission, reused across retries** (minted
  when entering review) so a resubmit dedupes server-side instead of double-creating a
  request.
- **2026-07-07 · `VITE_ALLOWED_ORIGINS` defaults to `"*"` for dev (fails open).** PROD MUST
  set it to real host origins. Documented POC trade-off, like the placeholder portal URL.
- **Deferred → V1 polish:** an expired session (`UNAUTHORIZED_SESSION`) maps to the generic
  failure copy without re-creating the conversation; `limit.reached` leaves the composer
  enabled (user can re-hit the cap). Both noted by the Phase 5 review.

## Phase 6 — unified requests + feedback (the write path)

- **2026-07-07 · Idempotency is scoped per (conversation_id, Idempotency-Key)**, not global —
  the same key in two conversations never collides (unique compound index). A duplicate key
  **replays the original result BEFORE re-validating** the payload (contracts §9), returning
  HTTP 200 with `duplicate: true`; the frontend branches on that flag (duplicate step vs
  success). Note: a schema-changed collection needs its old index dropped (a migration; the
  dev `requests`/`feedback` collections were dropped so the new compound index rebuilds).
- **2026-07-07 · `set_outcome` is an idempotent `$set` run on fresh AND replay**, so a request
  whose outcome write failed on the first attempt is reconciled when the client retries.
- **2026-07-07 · Feedback is one rating per message** (unique `(conversation_id, message_id)`
  index + upsert, last-write-wins) — a double-click/retry updates in place instead of
  spamming rows.
- **2026-07-07 · Input hardening:** `fields` are whitelisted per type (unknown keys dropped)
  and each value length-capped (4000); feedback `comment` capped (2000); Idempotency-Key
  length-capped — bounds storage/DoS and drops junk keys before persistence.
- **Deferred → V1:** Stripe-style key↔payload fingerprint binding (POC mints a fresh key per
  submission, so a reused key means the same request); checking the conversation exists / is
  active before filing a request (a stale token can currently file against a deleted
  conversation; `set_outcome` no-ops there).

## Phase 7 — read-only admin dashboard

- **2026-07-07 · PII is masked at READ time, not at store time.** Transcripts and unresolved
  questions keep the verbatim value in Mongo; the admin router masks emails/phones on the way
  out (`mask_pii_in_text`). This keeps the data available for a future audited reveal while
  the default admin view never shows raw contact info (contracts §10).
- **2026-07-07 · Masking covers email AND phone in all free text** (transcript content +
  unresolved questions). Email → `a***@acme.com`; phone → `***-***-NN` (last two digits). The
  phone regex only masks 7–15-digit runs, so short codes / 4-digit years survive; a date like
  `2026-07-07` is over-masked (harmless in an admin view — safety over precision). Structured
  request `contact.email` uses `mask_email`; `contact.name` is never exposed by the admin API,
  and `contact.company` is returned as-is (§10 scopes masking to email/phone).
- **2026-07-07 · Admin is HTTP Basic + constant-time compare on every route.** All five routes
  are GET/read-only and carry `AdminDep`; a bad/absent credential 401s with
  `WWW-Authenticate: Basic` and never echoes the configured password. Creds in the UI live in
  React memory only (no localStorage).
- **2026-07-07 · Admin UI is a second Vite entry** (`admin.html` + `src/admin/**`), fully
  separate from the widget bundle; the multi-entry build emits both `dist/index.html` and
  `dist/admin.html`.

### Deferred from the Phase 7 adversarial review

- **Default admin password guard → Phase 8.** `ADMIN_PASSWORD` defaults to the in-repo
  `dev-only-change-me`; a deployment that forgets to set it accepts a well-known credential
  that unlocks the whole PII surface. Phase 8 (hardening/POC exit) should fail startup when
  `env != dev` and any secret (admin password, `session_secret`) still equals its default.
  **Done in Phase 8** (fail-closed, see below).
- **Exotic-email regex gaps → accepted for POC.** The email regex requires an ASCII dotted
  domain + TLD, so internationalized (`用户@例え.jp`), single-label (`user@mailhost`), and
  IP-literal (`user@[192.168.0.1]`) addresses pass through unmasked. Standard public-support
  emails are covered; broadening (or an on-`@` heuristic) is a V1 refinement.

## Phase 8 — hardening & POC exit

- **2026-07-08 · Per-IP creation cap = fixed-window TTL counter, HMAC-keyed.** One doc per
  (HMAC(ip):window) in `rate_limits`, atomic `find_one_and_update` upsert+`$inc`, Mongo TTL
  purges expired windows. The IP is HMAC'd (never stored raw — §10). A fixed window can allow
  up to ~2x the cap across a boundary — acceptable for a coarse abuse cap. Over cap →
  `429 RATE_LIMIT` retryable. `client_ip` trusts leftmost `X-Forwarded-For` (POC deploy is
  behind a trusted proxy) else the peer.
- **2026-07-08 · Stale-lock recovery + heartbeat.** The send path clears a leaked lock older
  than `lock_stale_seconds` (120s) and retries `begin_turn` once; `scripts/sweep_locks.py` is
  the global cron sweep. A LIVE turn **heartbeats** its lock (~every `lock_stale_seconds/3`)
  so however slow it is, it stays young and is never swept — the atomic turn op (invariant #3)
  is preserved (heartbeat only refreshes `started_at`, never adds a second lock).
- **2026-07-08 · Fail-closed secret guard.** `ENV` now defaults to `prod`; startup rejects the
  in-repo default `SESSION_SECRET`/`ADMIN_PASSWORD`. Local dev, tests, and the compose api
  service set `ENV=dev` explicitly (`tests/conftest.py` forces it; `backend/.env` gets an
  `ENV=dev` line). A deploy that forgets `ENV` fails closed rather than booting insecure.
- **2026-07-08 · Log-hygiene = static + runtime.** Event messages must be static string
  literals (no f-strings/`%`-args); the formatter rejects `record.args` and any email in the
  event string, and an AST scan (`test_log_hygiene.py`) enforces it across `app/` + `scripts/`.

### Golden-gate tuning at POC exit (2026-07-08)

- **`must_use_canonical` is a hard gate ONLY for invariant-#8 mandatory topics** (pricing,
  security/compliance, AMI, portal, case studies, client-relationship/identity). For general
  topics (company/service/industry) the model may answer from grounded `search_knowledge` OR
  the canonical answer — both safe — so those cases now assert SAFETY (`must_not_contain`
  prices/guarantees) rather than a specific route. This removes model tool-choice non-determinism
  from the gate (it was flaking ~30/32 with a *different* general-topic case failing each run,
  while every safety assertion always passed) and aligns the gate with the project's own rule.
- **Pricing-routing nudge in the prompt.** A "ballpark / typical project number" sometimes routed
  to `unsupported`; the prompt now states any cost/budget/ballpark/estimate question is the
  `pricing` intent (a mandatory-canonical topic), never unsupported. Real gate: 32/32.
- **`sla_001` bans a commitment, not a mention.** "Can you guarantee delivery in two weeks?" —
  a correct refusal ("I can't guarantee a two-week delivery") echoes the phrase, so the bare
  `two weeks` ban was a false positive; retuned to affirmative-commitment phrases (same pattern
  as the Phase 4 fix). `eval/run.py` gained `--show` to print each case's response + routed intent.

### Deferred from the Phase 8 adversarial review (→ V1)

- **Dedicated rate-limit HMAC secret.** The limiter reuses `session_secret` to hash IPs. Two
  independent one-way HMACs, no crypto cross-talk — a key-hygiene nicety, not a defect.
- **`SESSION_EXTRA_SECRETS` not covered by the guard.** The startup guard checks
  `session_secret`/`admin_password` but not retired keys in `session_extra_secrets` (which
  default to empty, so no in-repo placeholder ships). Extend if that ever gets a default.
- **Edge/CDN rate limiting.** The app-level per-IP cap is coarse; users behind one NAT share a
  bucket. Tunable via `IP_CREATE_CAP`/`IP_CREATE_WINDOW_SECONDS`; edge limiting is the V1 shape.

### Top V1 item — mid-conversation action chips (found in Checkpoint 8 smoke)

- **The strategy-call form only surfaces from the welcome chip, not mid-conversation.** Suggested
  actions (which the widget turns into the form) come ONLY from a tool's `allowed_action_ids`
  (`orchestrator` → `resolve_actions`). When the model recognizes a booking intent and answers in
  free text WITHOUT calling a canonical/tool that carries `strategy_call`, no chip is attached, so
  the form never opens — the bot dead-ends asking for name/email as text (which it then correctly
  refuses to collect in chat). Repro: user asked to "book a call" several turns in; every reply was
  text, no form. **V1 fix (no new tool — invariant #2):** add a canonical answer for the
  booking/scheduling intent whose `allowed_action_ids` includes `strategy_call`, and route
  "book/connect/schedule a call" to it in the prompt so the reply always carries the action chip.
  Broader than the earlier `dsc_001` note (any booking intent, not just discovery).

## Phase V0 — foundation & staging environment (V1 build)

- **2026-07-08 · `ENV` defaults to `prod`; non-dev fails closed on incomplete config.** `staging`/
  `prod` refuse to boot without real `SESSION_SECRET`/`ADMIN_PASSWORD`/`OPENAI_API_KEY`/
  `OPENAI_VECTOR_STORE_ID`, a non-localhost `MONGO_URI`, and https non-localhost `CORS_ORIGINS`.
  CORS + Mongo are validated by parsed host (reject `*`, http, localhost/127.0.0.1/::1), and
  secrets are stripped so whitespace-only values are caught (Phase V0 review, HIGH: CORS
  exact-string fail-open).
- **2026-07-08 · `/healthz` is a minimal public probe; env/build/flags live behind admin.**
  `GET /api/v1/admin/system` (admin auth) exposes env/build/feature-flags so an unauthenticated
  caller can't fingerprint the deployment. The dev stream-test router mounts only in dev.
- **2026-07-08 · Staging = one DO Droplet (Demo team) + docker-compose + Caddy** (`flush_interval -1`
  keeps SSE unbuffered). Verified live: env=staging + token-by-token streaming over HTTPS. Runbook
  `docs/DEPLOY_STAGING.md`; a dedicated staging OpenAI project is a deferred refinement (staging
  currently reuses the dev key/store).

## Phase V1 — agent controls & retrieval hardening

- **2026-07-08 · Model fallback is transparent and only-before-first-output.** The adapter tries the
  primary model; on `MODEL_UNAVAILABLE` *before any delta streams*, it retries once on
  `OPENAI_FALLBACK_MODEL`. A **mid-stream** failure is NOT retried — replaying would duplicate
  output. Fallback is opt-in (empty = none). The `Completed` event reports the model that actually
  answered, so the fallback is observable.
- **2026-07-08 · Per-message trace metadata.** Each assistant message records `prompt_version`,
  `model` (the fallback if used), and a per-turn `trace_id`; the turn-completed log carries the same
  plus token counts + latency (no PII/content). Surfaced in the admin conversation detail. (The
  conversation-level `model` is set at create; the per-message `model` is authoritative for the turn.)
- **2026-07-08 · Retrieval relevance threshold.** `RETRIEVAL_MIN_SCORE` drops hits below the score
  before grounding (0.0 = keep all; tuned per env against the store's distribution). All hits below
  threshold → `empty`, not `unavailable`. Category metadata filters already existed.
- **2026-07-08 · Vector Store promotion = per-env stores, not shared.** `upload_knowledge.py` runs
  against an env's OpenAI project (via `get_settings()` key) and mints a store id set in that env's
  `OPENAI_VECTOR_STORE_ID`. Promotion = re-upload approved content to the prod project's store; never
  edit prod content in place. The golden gate (CI `golden-eval` job, its `OPENAI_VECTOR_STORE_ID`
  secret pointed at the target store) must pass on the target config before promotion.

## Phase V2 — content lifecycle & mid-conversation booking

- **2026-07-08 · Mid-conversation booking fix (top V1 item).** A booking request now routes to a
  canonical answer for the `strategy_call` intent whose `allowed_action_ids` includes `strategy_call`,
  so the reply carries the booking chip → the widget opens the strategy-call form (the SAME
  `handleSelectAction` handles welcome chips and mid-conversation actions — no frontend change). No new
  tool (invariant #2). The prompt routes "book / schedule / connect with a strategist or sales" to
  `strategy_call` and explicitly says NOT to collect name/email/phone in chat. Real gate: `bok_001`,
  `bok_002` (the multi-turn Checkpoint-8 repro) pass.
- **2026-07-08 · Canonical `status` is set ONCE on insert; only `approve()` transitions it.** `upsert`
  `$setOnInsert`s status, so re-seeding content (even `seed_canonical.py --status draft`) never
  downgrades an approved answer — closing the review's HIGH where `--status draft` would have
  mass-downgraded the whole baseline and silently disabled every canonical answer.
- **2026-07-08 · Draft→approved lifecycle has an operator path now.** `seed_canonical.py --status draft`
  stages content; `scripts/approve_canonical.py --intent X` promotes it (wires `repo.approve`). The
  admin approval UI is still Phase V5; the CLI keeps the draft flow from being a dead-end.
- **2026-07-08 · Sales booking vs support escalation are distinguished in the prompt.** "Book / connect
  with a strategist or sales" → `strategy_call`; a "problem / complaint / account issue with a person"
  → the escalation path (`human_escalation`), so a support-seeker isn't funneled into the sales form.
  Guarded by new golden case `hec_001`. Real gate after V2: **35/35**.
- **Deploy note:** a deployment must re-run `seed_canonical.py` after V2 or `get_canonical_answer(strategy_call)`
  returns unmatched and the booking dead-end returns (only `bok_001` catches it). Reseed on every content change.

## Phase V3 — background worker & durable job model

- **2026-07-08 · Job queue per contracts §7-8.** `jobs` collection + `JobRepository`: the claim is a
  single atomic `find_one_and_update({status:pending, available_at≤now}, {$set running, lock_owner,
  lock_expires_at}, $inc attempts)` (exactly-once, index-backed), retry-with-backoff → dead-letter, and
  a lease so a crashed worker's job is reclaimed. Dedicated worker `app/worker.py` (`python -m app.worker`):
  reclaim → schedule due periodic jobs → drain claims → dispatch by type; graceful shutdown on SIGTERM;
  queue-depth/dead-letter monitoring. Periodic tasks (all idempotent): stale-lock sweep, abandonment
  sweep, daily aggregates, knowledge-review reminder.
- **2026-07-08 · Adversarial-review hardening (2 HIGH + fixes).** (H1) `reclaim_expired` now dead-letters
  a budget-exhausted expired-lease job instead of looping forever — the poison-pill guard for a job that
  hard-crashes the worker before `fail()` runs (matters for the V4/V5 network handlers). (H2) `complete`/
  `fail` are guarded on `{lock_owner, status:running}` and no-op if the lease was reclaimed, so a slow
  worker can't clobber the reclaimer's result (mirrors the turn-lock's run_id guard). (M5) a hard per-job
  timeout `worker_job_timeout_seconds` (< lease) so a hung handler can't wedge the loop or outlive its
  lease. (M6) a `{type,status}` index + a TTL on `terminal_at` so terminal jobs are pruned and the
  scheduler's dedup check is index-backed.
- **2026-07-08 · Accepted for V3, noted for multi-worker V1 deploy:** no per-job heartbeat (M3) and the
  scheduler's check-then-act dedup (M4) can in principle double-run a periodic job across two workers —
  harmless here because every periodic task is idempotent AND staging runs a single worker. Multi-worker
  prod should add a job heartbeat and an atomic enqueue-if-absent (partial unique on the pending state).
- **Deploy:** staging adds a `worker` service (same image, `python -m app.worker`). Job types
  `deliver_request`/`poll_indexing`/`retention_sweep` have no handler yet (land in V4/V5/V6).
