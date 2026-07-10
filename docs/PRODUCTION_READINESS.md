# Production Readiness & Scale — Cadre AI Support Chatbot

**Status:** Assessment + forward plan. Companion to `V1_EXIT_REPORT.md` (the go/no-go) and
`SECURITY_REVIEW_V1.md` (the residual-risk register R1–R9).
**Premise:** V1 is **engineering-gate-ready** (V1 exit: GO), not yet **running in production**. This
document separates what stands between the two — turn-on gaps, scale/resilience hardening, and the
long-run maintenance metabolism — and prioritizes them (§7).
**Grounded in:** `V1_EXIT_REPORT.md`, `SECURITY_REVIEW_V1.md`, `deploy/Caddyfile.prod`,
`app/agent/adapter.py` (fallback + degraded mode), `app/core/config.py`, and the scaling sequence in
`03_Architecture_and_Decision_Records.md` §7.

---

# 1. Gate-ready ≠ running

Three kinds of work stand between "gate-ready" and "running in production" — different owners, different
risk:

- **A — Stand-up (turn it on).** Built but not live: stand up the prod environment (domain + prod OpenAI
  project), wire the alerting tool to the existing `GET /api/v1/admin/monitoring` endpoint, provision the
  dedicated prod MongoDB + a scheduled restore drill, publish approved content, connect real CRM/ticket
  destinations. These are the open `V1_EXIT_REPORT` items — external-owner decisions + provisioning, not
  engineering.
- **B — Harden (scale & resilience).** What changes for many concurrent users and provider failure: the
  edge WAF, a per-instance concurrency ceiling, proactive provider rate-budgeting, a spend circuit-breaker,
  connection-pool sizing.
- **C — Endure (the long run).** What degrades or grows over months and years: data growth, cost drift,
  model deprecation, the `motor` driver EOL migration, content staleness, and the aging of the golden set
  and security posture.

**Two hard gates before public traffic** (both infrastructure, both from the security review):

1. **Edge WAF/CDN** in front of Caddy — volumetric / bot / edge-rate protection (`SECURITY_REVIEW_V1` R2,
   gating).
2. **Production IdP** for admin — per-user attribution, MFA, revocation, replacing the shared Basic
   credential (R1). Also the bridge to V2 authenticated customers (`07_V2_Authenticated_Capability_Plan.md`).

---

# 2. Security at public exposure

## 2.1 The edge — WAF and load balancer

**Load balancer: already built.** Production runs **≥2 stateless API replicas behind Caddy** with dynamic
round-robin upstreams, active health checks, and in-request retry, so a rolling deploy never surfaces a 502.
SSE is **unbuffered** (`flush_interval -1`) and **pins to one replica for the life of the stream** — safe
because MongoDB is the single source of truth. At larger scale, front multiple edge nodes with a dedicated
LB (DO LB / cloud LB); the app is LB-ready unchanged.

**WAF: the layer public exposure requires.** It sits *in front of* Caddy and owns what the application
deliberately does not:

| Threat | App does today | WAF/CDN adds |
|---|---|---|
| Volumetric flood / DDoS | per-IP + per-session caps (single-source only) | absorbs distributed / rotating-IP floods |
| Headless-bot spam | nothing above the caps | bot mitigation (Turnstile/hCaptcha on conversation-create) |
| Edge rate-limiting | app-level fixed-window | coarse filtering before traffic hits the app |
| Reputation / geo | — | IP reputation, geo rules, optional TLS offload |

The app caps are **defense-in-depth behind the WAF, not a substitute**. On cutover, set
`TRUSTED_PROXY_HOPS=2` so per-IP caps read the real client IP through the CDN (`core/net.py`). Without the
WAF, a distributed flood or bot swarm can drive denial-of-wallet even though single-source abuse is blunted.

## 2.2 The rest of the security stand-up

- **Production IdP** (OIDC/SAML) replacing the shared admin Basic credential (R1).
- **Secrets manager** (DO App Platform secrets / Vault / SOPS) + a rotation runbook, replacing gitignored
  `deploy/*.env` on the host (security review §5a).
- **Audit hardening** — the trail is append-only *by convention*; add a hash-chain or external WORM store and
  scope the app's Mongo role so it cannot mutate `audit` (R3).
- **Verify the CSP** on the deployed origin (present and safe, not yet browser-verified in prod — R9); set
  `frame-ancestors` for the widget (R5).

## 2.3 Prompt injection — the strong part

Holds **by construction**: the model is read-only and out of the write path; suggested actions are IDs from
an app allowlist (never parsed from model text); only human-approved canonical content serves; retrieval is
an approved-source allowlist and chat content is never ingested; the system prompt instructs the model to
ignore injected instructions; and the **golden set includes injection probes as a release gate**.

Add for production: an optional **input/output moderation pass** (accepted as skippable for a read-only bot
with no XSS sink, but cheap insurance at public scale); **flag insights-owned draft FAQs as untrusted** in
admin (attacker text reaching the summarizer can queue an *unserved* draft — a reviewer social-engineering
surface); and keep the injection-probe suite growing as content and tools grow.

The stakeholder frame: the AI-specific risk that usually scares people about public LLMs — jailbreaks,
exfiltration, the model *doing something* — is the part this design handles best. The production work here
is ordinary web-app hardening, not AI risk.

---

# 3. Scale — many users chatting at once

The API holds no local state, so it scales horizontally. The limits are specific and known.

```
browser (SSE) → WAF/CDN → Caddy LB (health-gated round-robin) → API replica ×N (stateless) → Mongo primary
                                              add replicas ↑ freely                             ← shared bottleneck
```

| Limit | Reality | For scale |
|---|---|---|
| API compute | stateless → linear horizontal scale | add replicas; autoscale on CPU / active-stream count |
| **Per-instance concurrent streams** | **no ceiling today** — unbounded SSE + in-flight calls per instance (R4) | add a per-instance concurrency cap + graceful shed (503 / limit message), so a spike sheds the marginal stream, not all of them |
| Mongo primary | one atomic write per turn — the shared backpressure point | managed cluster; connection-pool sizing; then read optimization |
| Connection pool | `motor` defaults, untuned | set explicit `maxPoolSize` per replica so N replicas don't exhaust Mongo connections |

Scaling sequence (doc 03 §7), cheapest lever first:
`indexes → production cluster → worker → more API instances → aggregates → read optimization → broker only
with measured need`. The highest-value single add is the **per-instance concurrency ceiling** — without it,
a traffic spike degrades *every* live conversation rather than shedding the marginal ones.

---

# 4. Data & analytics at scale

**MongoDB.** Growth is **bounded by design** — the 40-message cap keeps conversation documents far under the
16 MB limit, and retention sweeps + conditional TTL indexes auto-purge abandoned/expired data. Attention at
scale: connection-pool sizing; the managed cluster with **backups + a tested restore drill** (a gate item);
and moving heavy read traffic to secondaries. Sharding only with measured need.

**Analytics.** All worker-owned, batched, and capped — so they never touch the chat path. Two things to know
at volume: the `$unwind` aggregations (funnel, usage-by-model) run on the primary and can **contend** → move
to secondary reads or lean on the pre-computed daily aggregates; and insights analyzes a **sample**
(`insights_batch_limit=300`/run), so at high volume it shows trends, not every conversation. A dedicated
analytics store / warehouse is deferred "only when justified" (doc 02 §6) — the funnel + insights +
`llm_usage` rollups live in Mongo until they demonstrably outgrow it.

---

# 5. Provider resilience — rate limits, outage, fallback

| Scenario | What happens today | Add for scale |
|---|---|---|
| Transient 429 / 5xx / timeout | the provider SDK auto-retries with exponential backoff + honors `Retry-After` (default 2 retries) | fine for spikes; nothing required |
| Sustained rate limiting at scale | after SDK retries → `MODEL_UNAVAILABLE` → one fallback-model attempt → degraded message. **No proactive rate-budgeting.** | a token-bucket / concurrency limiter to stay under TPM/RPM *before* hitting 429s; request shedding under pressure; tier up account limits pre-launch |
| Primary model fails pre-stream | retries once on the approved **fallback model** (only before first output — never mid-stream, which would duplicate) | automate **cross-provider** failover (the OpenAI→Anthropic→OpenRouter switch exists but is admin-manual today) |
| Full provider outage | **degraded mode**: canonical answers serve deterministically *without* the model; portal + all forms keep working; approved limitation message for generative answers | nothing required — this already works |
| Runaway spend | the budget is an **alert, not a brake** (R4) | a global spend circuit-breaker that throttles at the ceiling |

Why the outage story is strong: because canonical answers serve *without* the model and forms/portal are
browser-driven, an outage degrades the bot to "approved answers + working contact paths" rather than taking
it down; and provider isolation makes switching to Anthropic or OpenRouter a golden-gated config toggle
(invariant #4, #15). The two real gaps are **proactive rate-budgeting** and a **spend brake** — both small,
well-scoped additions.

---

# 6. The time horizon — what degrades, grows, and must be maintained

A production LLM system has a maintenance metabolism; the load-bearing question over time is not the code —
it is whether someone **owns the recurring work**.

**~3 months (settle in).** Wire the alerting tool to the monitoring endpoint — you cannot run blind (open
gate item). Tune WAF + rate caps to the real traffic shape; add bot mitigation if abuse appears. First cost
reconciliation vs. the budget alert; confirm retention/TTL sweeps are actually running and stay bounded.
First content-staleness pass — canonical answers vs. the live site.

**~6 months (optimize).** Volume likely justifies **enabling prompt caching** — the biggest cost lever
(~85% of input tokens are the repeated static system prompt). Re-run the golden gate against current model
prices/limits; correct `LLM_PRICING`. Move contending analytics aggregations to secondary reads / daily
aggregates. Establish the knowledge-review cadence (the worker already schedules reminders).

**~1 year (maintain).** **Model deprecation is real** — `gpt-5.4-mini` / `claude-haiku-4-5` will age and
providers retire model IDs; versioned config + the golden gate make migration safe, but it is a planned,
recurring task — don't get caught by a forced sunset. **Migrate `motor` → PyMongo Async** (the driver is
EOL-bound; flagged since V1, still pending; contained behind the repository interface). Dependency +
security patch cadence (FastAPI, SDKs, Caddy); a periodic security re-review. Possibly begin the V2
authenticated build (doc 07).

**1–3 years (evolve).** Accumulated (retention-bounded) conversation + attribution data becomes an
**asset** — the close-loop attribution flywheel (doc 07 §13), possibly a curated dataset (a V1.5 item).
The provider landscape shifts substantially — **provider isolation + the golden gate is what lets you ride
it** (swap models/providers without a rewrite). Scale with measured need: read replicas → possibly sharding;
a broker only if job volume demands; the agent-framework re-evaluation (Agents SDK / LangGraph) at V2 (ADR-020).
**Ownership is the real variable** — on-call, the golden set, content approval, the security re-review, cost
watch. The system is only as production-ready as the team running it.

---

# 7. The readiness register (prioritized)

Severity: 🔴 gate / high · 🟡 medium · 🟢 lower.

| Pri | Item | Kind | Why |
|---|---|---|---|
| 🔴 | Edge WAF / CDN in front of Caddy | gate | volumetric/bot; denial-of-wallet (R2). Set `TRUSTED_PROXY_HOPS=2` on cutover |
| 🔴 | Production IdP for admin | gate | per-user attribution, MFA, revocation (R1); V2 bridge |
| 🔴 | Stand up prod env + wire alerting | stand-up | domain + prod OpenAI project + dedicated Mongo + tested restore |
| 🟡 | Per-instance concurrency ceiling + graceful shed | scale | shed the marginal stream, not all of them (R4) |
| 🟡 | Provider rate-budgeting + spend circuit-breaker | scale | stay under TPM/RPM; turn the budget alert into a brake (R4) |
| 🟡 | Automated cross-provider failover | resilience | the switch exists; automate the trigger |
| 🟡 | Secrets manager + audit WORM + CSP verify | security | close the security-review residuals (§5a, R3, R9/R5) |
| 🟢 | Enable prompt caching · connection-pool sizing | cost/scale | biggest cost lever; prevent replica pool exhaustion |
| 🟢 | `motor` → PyMongo Async · model-migration cadence | durability | retire EOL debt; stay ahead of model sunsets |

---

# 8. The verdict

Production readiness here is **mostly turning things on and adding two edge/resilience layers** — not a
rewrite. The architecture already did the hard part: stateless (horizontal scale), provider-isolated
(swap models without a rewrite), degrade-gracefully (canonical answers survive an outage), and bounded data
(caps + retention). The two hard gates (WAF, IdP) are infrastructure decisions; the scale hardening is a
handful of well-scoped additions; and the long-run cost is **ownership of the maintenance metabolism**, not
surprise rewrites.

---

# 9. References

- `V1_EXIT_REPORT.md` (gate items + go/no-go), `SECURITY_REVIEW_V1.md` (R1–R9 residual risks + §5a
  recommendations).
- `03_Architecture_and_Decision_Records.md` §6 (degraded operation), §7 (deployment + scaling sequence);
  ADR-020 (agent runtime).
- `deploy/Caddyfile.prod`, `deploy/docker-compose.prod.yml`; `RUNBOOK_PROD.md`, `DEPLOY_PROD.md`.
- `07_V2_Authenticated_Capability_Plan.md` (the IdP/tenancy work that also unlocks V2; §13 attribution).
- `CLAUDE.md` invariants (#2 read-only model, #4 provider isolation, #5 log hygiene, #11 async delivery,
  #15 gated model/provider changes).
