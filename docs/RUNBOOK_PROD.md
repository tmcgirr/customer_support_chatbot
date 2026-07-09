# Production Runbook — Cadre AI Support Chatbot

Operating the V1 production service: monitoring/alerts, backups, secrets, scaling, and
incident response. Deploy mechanics are in [`DEPLOY_PROD.md`](DEPLOY_PROD.md).

## Monitoring & alerts

Scrape `GET /api/v1/admin/monitoring` (admin Basic auth) on an interval — it returns
IDs-only counters (no PII). Structured worker logs (`worker.queue`, `worker.job.*`) also
carry queue depth and per-job status. Recommended alerts:

| Signal | Source | Threshold | Why |
|---|---|---|---|
| `dead_letter` | /monitoring | **> 0 → page** | A job exhausted its retries — delivery/erasure needs a human. |
| `delivery_failed` | /monitoring | **> 0 → page** | Parked request(s) awaiting admin redeliver (external system down). |
| `privacy_failed` | /monitoring | **> 0 → page** | A verified erasure could not complete — legal-sensitive. |
| `queue_depth` | /monitoring | sustained **> 100 → warn** | Worker not draining (crashed / overloaded). |
| HTTP 5xx rate | proxy/app logs | **> 1% over 5 min → warn** | API or model degradation. |
| p95 turn latency | `chat.turn.completed` log `latency_ms` | **> 15 s → warn** | Model slow / retrieval slow. |
| `/healthz` | LB health check | non-200 → replica out of rotation | Caddy already health-gates upstreams. |

The model auto-falls back to `OPENAI_FALLBACK_MODEL` on `MODEL_UNAVAILABLE` before any
output streams; a spike in fallback usage (in `chat.turn.completed` `model`) is a soft
signal the primary model is unhealthy.

## Backups & restore

- **Backups:** managed Atlas provides continuous backups; for self-hosted, schedule
  `scripts/backup_mongo.sh` (cron/systemd timer) to off-host storage. Keep ≥ 7 daily +
  ≥ 4 weekly.
- **Restore drill (do monthly):** restore the latest archive into a SCRATCH database and
  compare collection counts — an untested backup is not a backup.
  ```bash
  MONGO_URI="$PROD_MONGO_URI" ./scripts/restore_mongo.sh cadre-<stamp>.archive.gz \
    --nsFrom='cadre_chatbot.*' --nsTo='cadre_restore_test.*'
  # verify counts, then drop cadre_restore_test
  ```
- **Real recovery:** `restore_mongo.sh <archive> --drop` into the live DB (prompts to
  confirm). Put the app in maintenance first.

## Secrets rotation

- **Session HMAC** — zero-downtime via the key ring: add the new key as `SESSION_KEY_ID` +
  `SESSION_SECRET`, keep the old under `SESSION_EXTRA_SECRETS` (`kid:secret,…`) so
  in-flight tokens still verify, then drop the old key after the max session lifetime.
- **Admin password / viewer password** — update `prod.env` (or the secrets manager) and
  redeploy the api. The fail-closed guard rejects a placeholder/weak value on boot.
- **OpenAI key** — rotate in the prod project; update `OPENAI_API_KEY`; redeploy.
- Never commit secrets; `deploy/*.env` is gitignored (only `*.env.example` is tracked).

## Scaling

The API is stateless (MongoDB is the source of truth) — scale horizontally:
`docker compose -f deploy/docker-compose.prod.yml --env-file deploy/prod.env up -d --scale api=N`.
Caddy's dynamic upstreams pick up replicas within `refresh` (10 s). The **worker is a
singleton** — its atomic job claim + lease make a second instance safe, but one supervised
worker is sufficient; run a standby only for HA (both will contend safely).

## Incident response

- **Delivery to CRM/ticketing failing** → `delivery_failed` / `dead_letter` rise. Fix the
  external system, then admin **redeliver** the parked requests (re-enqueues a job; the
  delivery service probes before re-sending, so no double-send). The `delivery_reconcile`
  sweep also re-enqueues lost/orphaned requests.
- **Erasure stuck** → `privacy_failed > 0`, or a verified request stays `open`. The
  `privacy_reconcile` sweep re-enqueues lost erasures; a dead-lettered one is marked
  `failed` for manual follow-up (re-run the `privacy_delete` job / escalate).
- **Conversation bricked at BUSY** → a leaked run-lock; the `stale_lock_sweep` job clears
  it, or run `scripts/sweep_locks.py`. A live turn heartbeats its lock, so only crashed
  turns are swept.
- **Model outage** → confirm `OPENAI_FALLBACK_MODEL` is set; the adapter fails over before
  output. Sustained outage: the widget shows the safe general-failure copy with retry.
- **Bad deploy** → roll back to the previous sha (DEPLOY_PROD "rollback").

## Data lifecycle (compliance)

Retention periods live in config and MUST match `docs/PRIVACY_NOTICE.md` — change them
together, with Legal/Privacy sign-off. Deletion requests are verified by an operator (admin,
audited) before the worker executes a single-store erasure; provider-retention terms are
documented, not deleted. Every reveal/redeliver/approve/verify/delete is in the append-only
audit trail (`GET /api/v1/admin/audit`).
