# Background worker & durable jobs

> **In one line:** A single dedicated worker process that runs everything that must happen *outside* a user's chat turn — external delivery, retention, analytics, sweeps — off a durable, MongoDB-backed job queue with retries and dead-lettering, no Redis or message broker.

**Status:** Live on staging  ·  **Introduced:** V1 (analytics jobs added in V1.5)

## What it is

The chat API answers users; anything slower, riskier, or side-effectful runs on the **worker** — a separate process (`python -m app.worker`) that shares the same codebase and repositories as the API. Work is modeled as **jobs**: rows in a Mongo `jobs` collection that the worker claims one at a time, runs, and marks done, retried, or dead-lettered. There is no external queue or broker; the job table *is* the queue. Some jobs are **periodic** (the worker's own scheduler enqueues them on a cadence); others are **on-demand** (API code enqueues them — e.g. "deliver this request", "poll this file's indexing").

## Why it exists

V1's trust boundary (CLAUDE.md invariant #11) forbids the model or the request handler from ever performing an external side effect inline. A user's request is persisted locally and returns success immediately; the *actual* handoff to a CRM or ticketing system happens later, asynchronously, so the user's success never depends on a third party being up. That requires a durable place to park deferred work with retries and a failure surface. The decision to build this on Mongo job documents rather than a broker is deliberate: [doc 03 ADR-011](../03_Architecture_and_Decision_Records.md) ("No Redis or broker initially") and [ADR-001](../03_Architecture_and_Decision_Records.md) (modular monolith — API and worker are separate *processes* of one codebase). A broker is explicitly deferred until measured need (doc 03 scaling sequence).

## How it works

Each worker loop **tick** does four things, in order:

- **Reclaim leaked leases.** Jobs whose worker crashed mid-run (lease expired) go back to `pending`; ones that already exhausted their attempt budget are dead-lettered on the spot (a poison-pill guard), and their type-specific reconciliation hook runs so the underlying resource never sticks silently.
- **Schedule due periodic jobs** from a fixed cadence table, deduped so at most one of each type is ever active (a "singleton" — a slow sweep never piles up behind itself).
- **Monitor** — every ~60s it logs queue depth and dead-letter counts and fires pageable ALERT logs when thresholds trip (IDs/counts only, never content).
- **Drain** up to 20 jobs: atomically **claim** the oldest-due pending job (`findOneAndUpdate` flips `pending → running`, increments `attempts`, stamps a lease), dispatch by type to a handler, then mark it `done`.

Failure handling is layered. A handler that raises is **retried with exponential backoff** (`base·2^(attempts-1)`, capped) until its attempt budget (default 5) is spent, then **dead-lettered**. Every run is wrapped in a hard **per-job timeout** that is kept strictly below the lease, so a hung handler can neither wedge the loop nor outlive its lease and get double-run. Long analytics handlers add a second, softer guard: a **whole-run wall-clock budget** that commits progress per item and stops cleanly before the hard timeout (draining a backlog over successive runs), plus a **per-call timeout** on individual model calls so one hung call can't blow the job budget. Ownership is checked on every state transition, so a reclaimed job can't be clobbered by a slow original owner. Deeper contract in [doc 04 §7](../04_API_and_Data_Contracts.md).

## Key files

- `backend/app/worker.py` — the worker process: the tick loop, the periodic-cadence table, per-job timeout + backoff, dispatch-by-type, and the dead-letter reconciliation hooks.
- `backend/app/domain/jobs/models.py` — the `Job` Pydantic model and the `JobType` / `JobStatus` enums (the authoritative list of job types).
- `backend/app/domain/jobs/repository.py` — the durable queue: atomic `claim`, `complete`/`fail` (retry vs dead-letter), `reclaim_expired` (leased-crash recovery), scheduler dedup (`has_active`), indexes + a TTL that reaps terminal jobs.
- `backend/app/domain/jobs/tasks.py` — the periodic task bodies (sweeps, aggregates, retention, privacy, labeling, summaries, insights, reconciliation), each idempotent and independently unit-testable.
- `backend/app/domain/delivery/service.py` — the `deliver_request` handler (at-most-once external delivery); provider SDKs stay isolated in `app/domain/delivery/adapters.py`.

## Interfaces

- **Worker entrypoint:** `uv run python -m app.worker` (one long-running process; graceful stop on SIGINT/SIGTERM).
- **Job types** (from `models.py`): `deliver_request`, `poll_indexing`, `retention_sweep`, `privacy_delete`, `privacy_reconcile`, `daily_aggregates`, `label_conversations`, `summarize_conversations`, `generate_insights`, `knowledge_review_reminder`, `stale_lock_sweep`, `abandonment_sweep`, `delivery_reconcile`.
- **Enqueue paths:** periodic types are enqueued by the worker's scheduler on a cadence; on-demand types (`deliver_request`, `poll_indexing`, `privacy_delete`, and the "Run now" `generate_insights` refresh) are enqueued by API/admin code.
- **Storage:** the `jobs` collection ([doc 04 §7](../04_API_and_Data_Contracts.md)); no HTTP surface of its own — visibility is via worker logs/alerts and the admin views of the resources jobs act on (delivery failures, privacy requests, indexing status).

## Status & limitations

- **Live on staging** as its own process on the DigitalOcean droplet, against DO Managed MongoDB (set via `staging.env`; the compose file otherwise falls back to an in-stack `mongo:7` for local dev) — schedules run, jobs claim/retry/dead-letter as designed.
- **Delivery is mock on staging.** The `deliver_request` job runs end-to-end, but the destination transport is a simulated client (see [request delivery](request-delivery.md)); no real CRM/ticketing is wired, pending destination decisions (doc 06 §6). The routing labels (`hubspot`, `zendesk`) are placeholders.
- **Single-worker assumption in practice.** The claim/lease design is *safe* for multiple workers (exactly-one-claims, reclaim-on-crash), but staging runs one worker; horizontal scaling is untried here.
- **Scheduler cadence is in-memory.** Periodic timing is tracked per running worker process, so a restart re-bases the cadence clock (the singleton dedup prevents pile-ups, so this is benign but worth knowing).
- Terminal jobs are pruned by a 7-day TTL index, so the `jobs` collection is not a long-term audit trail — durable records live on the resources themselves (requests, privacy requests, audit log).

## Future & scaling

- **Real delivery adapters** slot in behind the existing `DeliveryClient` boundary once destinations are chosen — no worker changes, just an adapter and the routing map.
- **Horizontal workers** are already supported by the atomic claim + lease; the next step is running more than one and confirming behavior under contention. Per doc 03's scaling sequence, a real queue/broker is only introduced "with measured need" — the Mongo queue is intended to carry V1/V1.5 load first.
- **Priority / fairness:** today the drain is strict oldest-`available_at` FIFO across all types; a bursty backlog of one type (e.g. indexing polls) shares the same lane as delivery. Type-aware priority or per-type concurrency would be a natural extension if one class ever starves another.
- **Config-tunable safety margins:** the lease, per-job timeout, backoff, and the **insights** budgets are settings, so tuning them for heavier load is a config change, not a code change (see `app/core/config.py`). The labeling/summary budgets are currently in-code defaults — worth promoting to settings before production.

## Related

- [Request delivery](request-delivery.md) — the `deliver_request` job and its at-most-once, dead-letter-to-admin flow (invariant #11, ADR-019).
- [Retention & privacy](privacy-and-retention.md) — the `retention_sweep`, `privacy_delete`, and `privacy_reconcile` jobs (invariant #13).
- [Conversation insights](analytics-and-insights.md) — the labeling/summarizing/insights jobs and their wall-clock budgets (V1.5).
- [doc 03 ADR-001, ADR-011, ADR-019](../03_Architecture_and_Decision_Records.md) · [doc 04 §7 jobs + §8 indexes](../04_API_and_Data_Contracts.md).
