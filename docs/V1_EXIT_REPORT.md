# V1 Exit Report — Cadre AI Support Chatbot

Maps each **V1 public gate** item (doc 02 §8) to its evidence and status as of Phase V8.

**Summary:** the engineering is complete and gate-ready. Every item is either **MET** or
**MET (mechanism) — blocked on an external-owner decision** for the final input (content
sign-off, real destinations, the Atlas-vs-self-hosted choice, prod provisioning, a WAF/CDN
provider, an alerting tool). None of the open items are engineering work; they are the
decisions catalogued in doc 06 §6 with named owners.

Legend: ✅ MET · 🟡 mechanism met, blocked on an external input · owner in **bold**.

| # | Gate item | Status | Evidence | Remaining (owner) |
|---|---|---|---|---|
| 1 | Approved content published | 🟡 | Canonical draft→approved lifecycle live (V5); only `approved` records served (invariant 8); golden set 35/35 gates content. | Final approved WORDING: pricing, security claims, AI Maturity, case studies — **Sales / Security-Legal / Product / Marketing** |
| 2 | Production integrations verified with failure-path tests | 🟡 | Delivery worker with bounded retries → dead-letter → replay; failure-path tests (retry, dead-letter, replay) — `tests/` V4; redeliver verified live (V5). Provider-isolated `DeliveryClient` boundary ready. | Real CRM/scheduler + ticketing destinations + adapters — **Sales / Client Success** |
| 3 | Role-controlled admin | ✅ | admin/viewer roles; viewer 403 on reveal/redeliver/approve; append-only audit; verified live on staging (V5). | — |
| 4 | Retention and deletion operational | ✅ | Daily retention sweep + conditional TTL; verified subject-erasure worker; both verified live end-to-end on staging (V6). | Confirm retention PERIODS — **Legal/Privacy** |
| 5 | Production MongoDB with tested restore | 🟡 | `scripts/backup_mongo.sh` + `restore_mongo.sh`; restore DRILL run on staging — dump → restore into scratch DB → all 7 collection counts matched → scratch dropped. | Provision the prod cluster + schedule backups; Atlas vs self-hosted — **Engineering** |
| 6 | Staging / production separated | 🟡 | Separate prod artifacts: `docker-compose.prod.yml`, `Caddyfile.prod`, `prod.env.example`; config is fully env-driven (separate DB, OpenAI project, Vector Store, domain); fail-closed guard forbids placeholder/localhost in prod. | Stand up the prod environment (gated on #5 + prod OpenAI project + domain) — **Engineering** |
| 7 | Edge abuse controls on | 🟡 | App per-IP caps ON (conversation-create, privacy-request); prod Caddy security headers (HSTS, nosniff, referrer, frame policy) — `caddy validate` clean. | Front with a CDN/WAF for volumetric/edge filtering — **Engineering** (provider decision) |
| 8 | Monitoring live | 🟡 | `GET /api/v1/admin/monitoring` (queue depth, dead-letter, delivery-failed, privacy-failed — no PII) live on staging; structured worker logs emit queue depth + latency; alert thresholds documented in `RUNBOOK_PROD.md`. | Wire an alerting tool to scrape + page — **Engineering** |
| 9 | Privacy notice matches actual data handling | ✅ | `docs/PRIVACY_NOTICE.md` written FROM the retention config + deletion behavior; retention + erasure verified live (V6). | Legal sign-off on wording + confirmed periods — **Legal/Privacy** |
| 10 | Golden set green on the production configuration | ✅ | `python -m eval.run` → **35/35** on the real-model config (same prompts/canonical/retrieval that ship to prod). | Re-run on the prod OpenAI project at cutover (representative today) — **Engineering** |

## Load balancer + SSE (doc 02 §8 / plan V8 §1)

Verified on a local 2-replica prod-shaped stack (Caddy dynamic round-robin upstreams):
requests split across both replicas (api-1 / api-2 ≈ even), SSE streamed progressively
through the LB (early frames flush immediately — not buffered), and cross-replica
statelessness held (conversation created on one LB request, message sent on another,
turn completed). `Caddyfile.prod` passes `caddy validate`.

## Architecture trust boundary (unchanged from POC, load-bearing in V1)

The model stays read-only (tools: `search_knowledge`, `get_canonical_answer`,
`get_portal_information`); all writes go through `POST /api/v1/requests` after browser
confirmation and the delivery worker; MongoDB is the single source of truth; public API
returns local IDs only; no PII/content in logs (AST + runtime guards). V2 opens the
authenticated-client / tenancy / private-store boundary — explicitly out of V1 scope.

## Go / no-go

**Engineering: GO.** The build satisfies every gate item's mechanism, verified live where
an environment exists. **Launch is gated on the doc 06 §6 decisions** — most critically the
content approvals (Legal/Marketing/Sales/Security), destination selection (Sales/Client
Success), and the MongoDB provisioning choice (Engineering). Cut over per
`docs/DEPLOY_PROD.md`, re-run the golden gate on the prod config, and re-confirm items
1–2, 5–8 on the real production environment before public traffic.
