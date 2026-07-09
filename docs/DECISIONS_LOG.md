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

## Phase V4 — asynchronous request delivery

- **2026-07-08 · Delivery is worker-owned and exactly-once (invariant #11).** `app/domain/delivery/`
  is a provider-isolated boundary (`DeliveryClient` → normalized `DeliveryResult`/`DeliveryError`; no
  SDK type escapes). On fresh request create the service enqueues ONE `deliver_request` job
  (flag-gated by `enable_delivery`; replay never re-enqueues). The `deliver_request` handler:
  already-delivered/failed → no-op; on a retry it first probes the destination
  (`find_by_reference`) and never blind re-sends; a transient error retries with backoff, a
  permanent/exhausted error PARKS `delivery_failed` (never a re-prompt). Request status:
  received → delivering → delivered / delivery_failed; `external_reference` is admin-only
  (invariant #6). Default `SimulatedDeliveryClient` until real CRM/ticketing destinations are
  selected (doc 06 §6).
- **2026-07-08 · Adversarial-review fixes.** (HIGH) a delivery job that terminated by a route the
  service didn't park (timeout, hard-crash, unexpected error) left the request orphaned in
  `delivering` — now the worker reconciles a dead-lettered `deliver_request` to `delivery_failed`,
  AND a periodic `delivery_reconcile` sweep parks stuck `delivering` requests (no active job) and
  re-enqueues `received` requests whose enqueue was lost (MED). (MED) the service now treats
  `delivered`/`delivery_failed` as terminal and `mark_delivering` is status-guarded, so a stray/re-run
  job can't resurrect + double-send a parked request. (MED) the `DeliveryClient` protocol documents
  that a real adapter MUST send `record.reference` as a server-side idempotency key (the probe is a
  best-effort secondary guard against replica lag).
- **Verified:** exactly-once claim, enqueue-once, probe-before-retry, provider isolation, PII/#6 all
  confirmed by the reviewer. 216 backend tests.

## Phase V5 — Admin V1: roles, audit, delivery ops

- **2026-07-08 · Roles are always enforced; the viewer is gated by `VIEWER_PASSWORD`, not a
  feature flag.** `admin`/`viewer` sit behind an IdP-replaceable dev-stub Basic auth
  (`AdminPrincipal`). Read routes use `AdminDep` (either role); reveal/redeliver/approve use
  `AdminRoleDep` (admin only) → a viewer is authenticated then **403**, never 401/200. Dropped the
  dead `enable_admin_roles` flag (fail-secure but misleading): enforcement can't be flag-disabled,
  and an empty `VIEWER_PASSWORD` simply disables the viewer login. The fail-closed prod guard now
  also rejects a placeholder `VIEWER_PASSWORD` (a weak one would grant read access to every transcript).
- **2026-07-08 · Audit is append-only and PII-safe.** `app/domain/audit/` exposes only
  `record`/`list_recent` (no update/delete). System fields carry local ids/intent only; the
  operator `reason` is free-text so it is **PII-masked at write** (`mask_pii_in_text`) — no email/phone
  lands in the trail at rest or via `GET /audit` (invariant #5).
- **2026-07-08 · Privileged actions validate → audit → act.** Each of reveal/redeliver/approve
  validates first (missing/non-eligible target → 400 with **no** audit and no side effect), then writes
  the audit record **before** the side effect, so an audit-write failure can never leave an un-audited
  reveal/redelivery/approval. Redeliver's reset is a status-guarded atomic update, so a double-click
  can't double-enqueue. Verified live on staging: viewer 403 on all three; admin reveal unmasked +
  reason masked in audit; approve publishes a draft; redeliver re-enqueues and the worker delivered
  it end-to-end; audit shows all three actions.
- **Deferred (non-security, to later phases):** cursor pagination on admin lists (plan V5 item 3);
  full knowledge file upload/replace/remove + indexing-status polling (only **approve** shipped —
  item 5); privacy-request management view (item 6 → Phase V6). The security-critical core (roles,
  audit, reveal/redeliver/approve) shipped and gates green. 232 backend tests + 31 frontend.

## Phase V6 — Privacy operations: retention, verified deletion, audit

- **2026-07-08 · Two deletion mechanisms with different semantics.** Bulk RETENTION expiry
  hard-deletes (a daily `retention_sweep` job, bounded per run; aggregates already snapshot
  the counts so history survives) — periods in `app/core/config.py` are PLACEHOLDERS pending
  Legal (doc 06 §6). Subject ERASURE (`privacy_delete`) uses a redacting TOMBSTONE (status
  `deleted`, PII stripped, skeleton + timestamps kept) so the erasure is provable and a
  delivered request's CRM reference stays known. Conversations are reaped by last_activity and
  requests by created_at; since last_activity ≥ a request's created_at, a converted conversation
  always outlives its request — no orphaned request.
- **2026-07-08 · Conditional TTL for anonymous walk-aways.** `mark_abandoned` stamps
  `expire_at = last_activity + anonymous period` ONLY on conversations that did not convert to a
  request (`$$REMOVE` for converted ones, keeping them out of the sparse TTL index); the TTL
  index auto-purges the rest. Converted conversations live to the long backstop with their request.
- **2026-07-08 · Deletion is verified, then worker-executed (invariant #13).** Public
  `POST /api/v1/privacy/requests` is unauthenticated and returns an identical ack to everyone
  (no existence leak), rate-limited per IP. It only RECORDS a request; an admin verifies identity
  out of band (audited) and that enqueues the `privacy_delete` job. Nothing deletes inline.
- **Adversarial-review fixes.** (HIGH) the abandoned-class retention delete reaped
  request-converted conversations at the 30-day anonymous period, orphaning their 365-day
  requests — now excluded via `exclude_outcomes=REQUEST_CONVERSION_OUTCOMES`. (HIGH) a
  subject-supplied `conversation_id` from the unauthenticated endpoint was erased unconditionally,
  letting a verified requester delete ANOTHER subject's transcript — erasure scope is now bound
  strictly to conversations of requests bearing the verified email; an unlinked named conversation
  is left for the operator. (MED) a `privacy_delete` that dead-lettered via lease-expiry
  (`reclaim_expired`) bypassed the fail hook and stuck the request `open` — `reclaim_expired` now
  returns the dead-lettered jobs and the worker runs the same dead-letter hook for both routes.
  (MED) a lost enqueue (crash between verify-commit and enqueue) left a verified erasure with no
  job — a periodic `privacy_reconcile` re-enqueues verified+open requests with no active job.
- **Accepted (documented) limitations.** (LOW) a crash in the narrow window between the erasure's
  redactions and its `mark_completed` may, on the retry, under-report the result counts in the
  audit record — the data is still fully erased and the request still completes; only the reported
  count is affected, so no transaction was added. A transcript whose only PII is a free-text email
  in a message, with no linked request and not named, is not reached by automated erasure (handled
  by the operator). Access-request fulfillment and a retry action for a `failed` erasure are
  operator-driven via the audited admin path (no self-service retry endpoint in V1).
- **Verified:** existence-non-leak, per-IP rate limit, role-gated + audited verify, subject
  isolation, idempotent replay, no PII in worker logs/audit (counts only) — by tests + review.
  249 backend tests + 7 admin frontend tests.

## Phase V7 — Experience & accessibility

- **2026-07-08 · Widget session persisted in sessionStorage for reload-resume.** The
  conversation id + session token are mirrored to sessionStorage so a page reload RESUMES the
  same conversation from the transcript endpoint (GET /conversations/{id}/messages) instead of
  starting over. Rationale vs invariant #9 (admin creds in memory only): the widget token is a
  short-lived, conversation-scoped HMAC — not a credential — and sessionStorage is per-tab and
  cleared on tab close; XSS could read the in-memory token anyway, so persistence adds no real
  surface. On true expiry (401) the stored session is cleared and the user recovers via "start
  new chat".
- **2026-07-08 · Dropped-stream reconcile is authoritative but count-guarded.** On an SSE close
  with no terminal event (or a mid-stream network drop) the widget fetches the transcript: a turn
  is treated as completed ONLY if the count of completed-assistant messages EXCEEDS the count
  captured before the turn — never merely "the last message is a completed assistant" (which could
  be the prior turn). If no new answer landed, the optimistic user bubble is preserved and retry
  offered (idempotent replay by client_message_id) — the question is never silently lost.
- **2026-07-08 · Citations are backend-flag-gated end to end.** Approved sources (title + public
  display URL only — no provider ids, invariant #6) are added to the completed SSE event and the
  transcript ONLY when `enable_citations` is on; the widget renders whatever sources it receives,
  so the single backend flag is the source of truth. Ships OFF (public citation behavior is a
  Product/Marketing decision, doc 06 §6). No golden impact (no prompt/canonical/text change).
- **Accessibility.** Two independent polite live regions: a visually-hidden role="status" for
  PROCESS (responding…/complete/failed/reconnecting, driven by a status-transition effect so a
  screen reader hears both start AND completion), and the message container as role="log"
  aria-relevant="additions" for CONTENT (new bubbles announced; streamed tokens don't spam).
  Focus moves to the composer on open and back to the launcher on close, with a Tab focus-trap;
  reduced-motion neutralizes animations; contrast audited (all WCAG AA, no changes). role="dialog"
  with aria-label; aria-modal dropped (the widget is non-blocking). axe: 0 violations.
- **Adversarial-review fixes (2 HIGH, 2 MED, 2 LOW — 0 false positives).** canSend now requires a
  live session so a create/resume failure disables the composer instead of silently swallowing a
  typed message; a create failure surfaces a create-capable "Try again" action (not a no-op
  Retry); handleExpired nulls the dead session refs and strips the in-flight streaming placeholder;
  reconcile uses the count-signal above and preserves the optimistic bubble; an empty resumed
  transcript starts fresh rather than showing a blank pane.
- **Blocked-on (build against placeholder):** production website integration + real privacy/portal
  URLs (Legal / Client Success) — wired via VITE_PRIVACY_URL / VITE_PORTAL_URL config with
  placeholders; public citation behavior (Product/Marketing) — shipped with the flag OFF.
- **Verified:** 42 frontend tests (resume-on-mount, expiry recovery, drop-reconcile success +
  misclassification guard, create-failure recovery, a11y axe) + 249 backend.

## Phase V8 — Production deployment & V1 public gate

- **2026-07-08 · Production is the staging shape, hardened.** `deploy/docker-compose.prod.yml`
  drops the in-stack Mongo (managed via MONGO_URI — Atlas-vs-self-hosted is Engineering's
  open decision), scales the stateless API behind a load-balancing Caddy (`Caddyfile.prod`,
  dynamic round-robin upstreams, SSE `flush_interval -1`, security headers), and supervises a
  single worker (atomic claim makes >1 safe; one avoids redundant scheduling). Verified on a
  local 2-replica stack: round-robin split, progressive SSE through the LB, cross-replica
  statelessness. Actual prod provisioning awaits the Mongo choice + prod OpenAI project + domain.
- **2026-07-08 · Monitoring is an admin-gated, IDs-only endpoint.** `GET /api/v1/admin/monitoring`
  exposes queue depth, dead-letter, delivery-failed, privacy-failed counts (no PII, invariant #5)
  for an alerting scraper; thresholds are in `docs/RUNBOOK_PROD.md`. Edge rate-limiting/WAF is a
  CDN provider decision; the app's per-IP caps are the baseline.
- **2026-07-08 · Backups have a tested restore.** `scripts/backup_mongo.sh` + `restore_mongo.sh`;
  the restore DRILL (dump → restore into a scratch DB → collection counts match → drop) was run
  on staging as the gate evidence, and is documented as a monthly runbook task.
- **Adversarial-review fixes (1 HIGH, 2 MED, 1 LOW; 2 false positives dropped).** (HIGH) the
  fail-closed guard only rejected the in-code default `dev-only-change-me`, NOT the `REPLACE_*`
  tokens the `*.env.example` files ship — so an operator who left a secret placeholder would boot
  prod with a repo-published admin password / session secret. `_is_placeholder` now rejects any
  value containing "replace" (plus empty / the dev default) across SESSION_SECRET, ADMIN_PASSWORD,
  VIEWER_PASSWORD, OPENAI_API_KEY, OPENAI_VECTOR_STORE_ID, and enforces a ≥16-char session secret;
  guard tests feed the actual example tokens. (MED) `/monitoring` + `/dashboard` unresolved count
  saturated at 1000 and materialized rows — replaced with a server-side `count_unsupported()`
  aggregation. (MED) `Caddyfile.prod` added passive health (`fail_duration`/`max_fails`) + in-request
  retry (`lb_try_duration`/`lb_try_interval`) so a rolling restart never surfaces a 502. (LOW)
  prod.env.example clarifies the fallback model must DIFFER from the primary.
- **Verified:** golden 35/35 on the real-model config; 257 backend tests; `caddy validate` clean.
  Go/no-go + the full gate→evidence mapping is `docs/V1_EXIT_REPORT.md`. Launch is gated on the
  doc 06 §6 external-owner decisions, not engineering.

## Infra — Staging migrated to DO Managed MongoDB (2026-07-09)

- **Staging now uses DO Managed MongoDB** (`cadre-staging-db`, nyc3, MongoDB 8, single node),
  reached over the public TLS endpoint with the cluster firewall locked to the `cadre-staging`
  droplet (trusted source). The in-stack `mongo` container is retained as a fallback until the
  managed setup is proven over time. Data migrated with `backup_mongo.sh`/`restore_mongo.sh`
  (dump → restore → all 7 collection counts matched); cutover proven by a live write landing on
  the managed cluster (13→14) while the container stayed at 13. Atlas Search is NOT needed —
  retrieval is the OpenAI Vector Store; Mongo is a plain document store (confirmed by grep).
- **Compose cutover mechanism:** `docker-compose.staging.yml` sets
  `MONGO_URI: ${MONGO_URI:-mongodb://mongo:27017/cadre_chatbot}` (requires `--env-file`), so the
  managed URI in `staging.env` wins when present and the container is the fallback otherwise —
  a one-line, reversible cutover.
- **Operational gotchas (also apply to prod cutover — see DEPLOY_PROD/RUNBOOK):**
  1. `doctl` cannot retrieve or reliably reset a **MongoDB** cluster's password — `connection`
     returns a URI with NO password, and `user reset` hands back a value that does not
     authenticate. Use the **DO UI → Connection Details** connection string as the source of
     truth; transfer it to the host via a hidden `read -rs` prompt (never through chat).
  2. The DO Mongo URI contains `&` (query params). Do NOT `. source` it in bash — `&` is a
     background operator and truncates the value. Read it with `grep '^MONGO_URI=' | cut -d= -f2-`
     and always quote it. `docker compose` `env_file:` parses it correctly (the app was fine).
  3. Point the URI's path at `cadre_chatbot` (DO defaults to `/admin`), keep `authSource=admin`.
  4. nyc1 managed-MongoDB provisioning was pathologically slow (>50 min) on 2026-07-09; nyc3
     provisioned normally. Same-metro, so co-location latency is a non-issue.

## V1.5 — Pluggable request-delivery transports (2026-07-09)

- **Delivery is now transport-pluggable, mock-by-default.** `DELIVERY_TRANSPORT` selects
  `simulated` (default — a functional MOCK that runs the whole pipeline, needs no creds, and
  shows in admin as `channel=simulated`), `webhook` (Slack/Teams incoming webhook, Zapier, or a
  CRM intake — httpx POST), or `email` (SMTP via stdlib smtplib in a worker thread). A neutral
  `format_request` renders one message all transports share, so the mock preview equals a real
  send. The worker picks the client via `build_delivery_client(settings)`; switching a real
  destination on is a config change, never a code change (invariant #4 provider isolation holds —
  httpx/smtplib types never escape the adapter). Admin surfaces a `delivery_channel` column.
- **Adversarial-review fixes (2 HIGH, 3 MED, 1 LOW; 0 false positives).**
  1. (HIGH) A misconfigured real transport used to fall back to the mock and silently drop every
     lead while admin showed "delivered". Now the fail-closed config guard REJECTS a real
     transport with missing creds in non-dev (dev keeps the permissive fallback).
  2. (HIGH) Webhooks/SMTP can't be de-duplicated and `find_by_reference` can't query them, so a
     retry after a possibly-successful send would double-deliver. Adapters now mark `retryable`
     ONLY when nothing could have been sent — a pre-send connection failure, or an explicit
     "not processed" status (HTTP 429/503); every ambiguous post-send outcome is PARKED for admin
     (invariant #11). The false "receiver dedupes on the idempotency header" docstrings are gone.
  3. (MED) 429 now retries (was parked). (MED) 3xx is treated as a failure (httpx doesn't follow
     redirects → nothing delivered). (MED) `httpx.InvalidURL` (not an `HTTPError`) is now caught so
     no provider type escapes. (LOW) email recipient/sender-refused is permanent, not retried.
- **Verified:** 278 backend tests (adapter classification per-status/per-exception, factory
  selection + non-dev fail-closed guard, provider isolation) + admin Channel column.

## V1.5 — Knowledge management (admin upload/approve/remove/replace) (2026-07-09)

- **A new admin Knowledge view manages the retrieval corpus at runtime.** Admins upload a
  document (stored but NOT searchable), then **approve** it — which ATTACHES it to the Vector
  Store. Serving is gated by *attachment* (retrieval queries the store directly; it never reads
  Mongo's `approved` flag), so approve is the true serving gate. **Remove** DETACHES; **replace**
  uploads a new (unapproved) file and retires the old. Same provider-isolation rule as retrieval:
  the OpenAI client, file ids, and errors never leave `app/domain/knowledge/store.py`
  (`KnowledgeStore` boundary — `SimulatedKnowledgeStore` default, `OpenAIKnowledgeStore` when a
  Vector Store is configured); the admin API exposes only the local `kbs_` id (invariant #6).
  A `poll_indexing` worker job watches ingestion to completion.
- **Adversarial-review fixes (6 confirmed, provider-isolation 0 findings, 3 rejected).**
  1. (MED) `poll_indexing` used the retry/backoff mechanism for "still ingesting", dead-lettering
     a healthy index after ~75s and firing a spurious CRITICAL page. Now: backoff is capped
     (`job_backoff_max_seconds=300`) and the poll gets a generous budget
     (`knowledge_index_poll_attempts=15` → ~45 min), and a genuine give-up reconciles the source
     to `indexing_status="failed"` via a new `_on_dead_letter` branch (truthful UI, not a stuck
     "Indexing…").
  2. (MED) `run_poll_indexing` ignored lifecycle, so a source removed/replaced (hence DETACHED)
     mid-index kept polling a 404ing file until it dead-lettered. Now it no-ops on
     `lifecycle != "active"`.
  3. (MED) Upload buffered the whole body before the 5 MB check. Now: a global middleware rejects
     any request whose `Content-Length` exceeds `max_request_body_bytes=10 MB` before routing/parse/
     auth (new `PAYLOAD_TOO_LARGE` code), and `_read_upload` reads only `MAX+1` so the handler
     never materializes an oversized body. (Document a proxy `request_body max_size` for the
     chunked/no-Content-Length case.)
  4. (MED) `approve` audited AFTER attaching (serving) — a failed audit-write would leave served,
     un-audited content (invariant #12). All content mutations (upload/approve/remove/replace) now
     **audit before the store mutation**, matching the codebase convention (redeliver/approve_canonical).
  5. (LOW) The admin UI showed unapproved (pending) sources as "Indexing…". Now unapproved reads
     "Not indexed"; "Indexing…" is reserved for approved+pending.
  6. (LOW) A 401 during an admin write showed an inline error instead of returning to login.
     `useAdminAction` now routes `AdminAuthError` to `onAuthError` (all admin views benefit).
- **Verified:** full backend suite (ruff + mypy + pytest, incl. new poll-lifecycle/dead-letter,
  oversized-body 413, and audit-before tests) + 45 frontend tests (build + vitest, incl. label +
  401-routing coverage).

## V1.5 — Conversation topic/intent labeling (analytics) (2026-07-09)

- **Ended conversations are labeled {topic, intent} by an async worker job, hybrid engine.**
  Rules first (a submitted request, or a canonical-answer hit → deterministic, no model $);
  the residue (open Q&A) is labeled by the model via a new provider-isolated
  `adapter.classify` (non-streaming, no tools, `store=False`). Labels live on the conversation
  doc and roll up into `daily_aggregates` + the admin Dashboard (`by_topic` / `by_intent`).
  Never on the request path; idempotent; a model failure leaves a conversation unlabeled to
  retry next run (never dead-letters). Cadence hourly; the `label_conversations` job is a
  scheduler singleton (deduped via `has_active`).
- **Adversarial-review fixes (4 confirmed; 3 rejected).**
  1. (HIGH) The rule map keyed off GUESSED canonical intents (`security`/`ai_maturity`/`portal`)
     instead of the real seeded ones (`data_security`/`ai_maturity_index`/`portal_access`), so
     the rule labeler silently never fired for 3 of its topics (pushed them to the paid model,
     and mislabeled the security+request case). Root cause the tests hid: they fed fictional
     intent strings. Now keyed by the actual `canonical_answers.intent` values (single
     intent→(topic,intent) map), and the tests use real intents.
  2. (MED) `batch_limit=200` × a serial model call each could exceed `worker_job_timeout_seconds`
     (50s) on a residue backlog → the job times out, retries, **dead-letters**, and fires a false
     CRITICAL page. Now each classify is bounded (`asyncio.wait_for`, 12s) and the run is bounded
     by a wall-clock budget (30s); progress commits per conversation, so the FIFO backlog drains
     over successive runs instead of dead-lettering.
  3. (MED) `Dashboard` called `Object.entries(rows)` with no null guard — a version-skewed
     backend omitting `by_topic`/`by_intent` would throw in render and (no error boundary)
     white-screen the whole admin console. Now `Object.entries(rows ?? {})`.
  4. (LOW) The `"unset"` (not-yet-labeled) bucket ranked #1 in the sorted "Top topics" / "Visitor
     intent" cards. Now excluded from those ranked cards.
  Also: `classify` uses `raise AdapterError() from None` (matches the module convention; no
  provider exception retained on `__cause__`).
- **Verified:** 314 backend + 45 frontend tests (rules on real intents, model-residue via
  FakeAdapter.classify, job idempotency + time-budget break, dashboard buckets, "unset" hidden).

## V1.5 — Conversation Insights: foundations (Slice A) (2026-07-09)

- **Feature = clustering + gap analysis + proposed FAQs + LLM insights summary** over ended
  conversations, scheduled daily + manual kickoff (plan.md "V1.5 — Conversation Insights").
  Owner decisions: **hybrid** clustering (embeddings pre-group → LLM name/analyze/propose) and
  **auto-draft** uncovered high-volume clusters into the existing canonical draft→approved gate.
- **Embeddings are an EPHEMERAL compute input, never persisted.** We batch-embed the run's
  questions, cluster in memory (`insights/cluster.py`, pure cosine/connected-components), and
  store only RESULTS (clusters, coverage, proposed drafts, summary) in `insights_reports`. So the
  "Mongo is a plain doc store / the only vector index is the OpenAI Vector Store" boundary holds —
  no vector storage or vector search is added to Mongo.
- **Cost scales with cluster count, not conversation count:** question extraction is heuristic
  (first substantive user message / verbatim unsupported question — no per-conversation model
  call); embeddings are ONE batched call; the LLM runs per-cluster (naming/coverage/proposal) +
  one summary. So a daily run over ~hundreds of conversations is a batched embed + a few dozen
  small LLM calls, bounded by a wall-clock budget under the worker job timeout.
- **Slice A shipped (dormant foundation, no behavior change):** `insights/` models + repository
  (dated `insights_reports`), `cluster.py` (+ unit tests), provider-isolated `adapter.embed`
  (batched, errors normalized, `from None`), `FakeAdapter.embed`, and config
  (`insights_*`: embed model, similarity threshold 0.82, min cluster size 3, window 7d, batch cap
  300, 40s budget). Pipeline (Slice B), dashboard (Slice C), review+deploy (Slice D) next.

## V1.5 — Conversation Insights: pipeline/dashboard + review fixes (Slices B-D) (2026-07-09)

- **Shipped (Slice B/C):** the pipeline (extract heuristic question → batched embed → in-memory
  cluster → per-cluster LLM {label, coverage, proposed Q/A} → daily-only auto-draft into the
  canonical approve gate → LLM summary → dated report), calendar periods (daily/weekly/monthly,
  idempotent per `period_type:period_key`, overlap by design), `generate_insights` job (scheduled
  + manual `POST /admin/insights/run`), and the admin **Insights** tab (report picker, coverage
  badges, proposed-FAQ approve, Run-now).
- **Adversarial-review fixes (11 confirmed).**
  1. (MED×3) `latest()`/`list_recent()` sorted by the composite `_id` (period-type prefix:
     weekly>monthly>daily lexically), so the "Latest" view showed a stale weekly over a fresh
     daily and dailies fell off the picker. Now sort by `generated_at`.
  2. (MED) Timeout: the shared budget was checked only BETWEEN clusters, and embed/summary ran
     unbudgeted → a run could exceed the 50s worker timeout → dead-letter. Now each embed/classify
     is `asyncio.wait_for`-capped (15s), the budget is 30s, and the summary is skipped when over
     budget — so a whole daily+weekly+monthly run stays under the timeout.
  3. (MED) Partial daily: a manual run before UTC midnight wrote `daily:<today>`, then the
     scheduled run SKIPPED it (exists), leaving the last-complete daily permanently missing the
     day's tail. `ensure_latest` now regenerates when `generated_at < period.end`.
  4. (MED×2) Auto-draft: audited AFTER the upsert, and the dedup intent hashed the
     NONDETERMINISTIC LLM label → duplicate drafts on retry/manual re-run. Now audit BEFORE the
     upsert (convention) and the intent hashes the STABLE representative question.
  5. (MED) Batch cap silently truncated a high-volume period to the oldest 300 with no signal.
     Now the report carries `conversations_in_period` (true total; > analyzed ⇒ sampled), logs a
     warning, and the UI shows "N of M (sampled)".
  6. (LOW) Run-now had no dedup → duplicate jobs/spend. Now guarded by
     `has_active_for_resource(..., "refresh")`.
  7. (LOW×2) UI: Run-now now disables during its own request; Approve-FAQ shows "Approved ✓" and
     hides the button after success (no confusing re-click 400).
- **Verified:** 336 backend + 47 frontend tests (ordering, partial-regen, stable-intent, dedup,
  timeout/truncation, approve/run-now UI). ruff + mypy clean.
