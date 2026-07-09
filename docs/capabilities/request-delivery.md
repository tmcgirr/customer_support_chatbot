# Requests & external delivery

> **In one line:** One unified endpoint captures every business request the visitor makes (book a strategy call, get portal support, escalate to a human), persists it locally, and a background worker delivers it to an external destination exactly once — mock by default, real transports one config flip away.

**Status:** Live on staging (simulated/mock transport)  ·  **Introduced:** V1

## What it is
When a visitor confirms a form in the chat widget — "yes, have someone call me," "I can't log into the portal," or "let me talk to a person" — the browser posts it to a single `requests` endpoint. The three request types share one collection, one lifecycle, and one code path (a `type` discriminator distinguishes them). Submission succeeds the moment the request is saved locally with a human-readable reference; getting it out to a CRM, ticketing system, or team inbox happens afterward, asynchronously, on the worker. Today that delivery runs end-to-end against a functional mock, so the full pipeline is exercised on staging without any third-party credentials.

## Why it exists
Cadre AI needs the bot to turn conversations into actionable leads and support tickets, but the visitor's success must not depend on a third party being reachable at that instant. The design decouples the two: the user gets an immediate confirmation once the record is durable, and the messy realities of external systems (timeouts, rate limits, ambiguous sends) are contained inside one background job with admin visibility. Folding three near-identical request types into one schema and endpoint is the other half of the decision — it collapses duplicated code and gives operators a single queue to watch. See [ADR-019](../03_Architecture_and_Decision_Records.md) (unified requests with asynchronous external delivery); the model is deliberately kept out of the write path per ADR-016.

## How it works
- **Persist-locally-first.** `RequestService.submit` validates the payload, normalizes a whitelist of per-type fields (dropping anything unexpected), stores a `RequestRecord`, and stamps the conversation's outcome. That local write is the user-facing success.
- **Idempotent submit.** An `Idempotency-Key` (unique per conversation) means a duplicate submission replays the original result with `duplicate: true` instead of creating a second request or a second delivery — enforced by a unique index (invariant #7).
- **Async, worker-owned delivery.** On a fresh create (and only when the `enable_delivery` flag is on), the service enqueues one `deliver_request` job. The worker runs `DeliveryService`, which drives status `received → delivering → delivered / delivery_failed`. The browser and the model never deliver (invariant #11).
- **Pluggable transports behind a boundary.** Delivery goes through a `DeliveryClient` — `simulated` (default mock), `webhook` (Slack/Teams/Zapier/CRM intake), or `email` (SMTP). The transport is chosen by config; provider libraries, types, and errors never escape the adapter (invariant #4). Every failure is normalized to a `DeliveryError` carrying a `retryable` flag.
- **Bounded retries → dead-letter, never a double-send.** Retryable failures back off and retry up to the job's attempt budget; a permanent failure, an ambiguous outcome, or an exhausted budget parks the request as `delivery_failed` for an operator. Because webhooks and SMTP can't be de-duplicated, any outcome that *might* have partially delivered is parked rather than blind-retried. See [doc 04 §7–8](../04_API_and_Data_Contracts.md) for the request/job contracts.

## Key files
- `backend/app/domain/requests/models.py` — the `RequestRecord`, its `type`/`status`/`destination` enums, and the bounded `Contact`.
- `backend/app/domain/requests/service.py` — validation, field whitelisting, replay-or-create, outcome write, and the single delivery enqueue.
- `backend/app/domain/requests/repository.py` — idempotent create/replay, delivery-state transitions, redeliver reset, and retention/erasure queries.
- `backend/app/api/public/requests.py` — the public `POST /api/v1/requests` endpoint (session check, idempotency, per-conversation + per-IP caps).
- `backend/app/domain/delivery/client.py` — the `DeliveryClient` protocol, `DeliveryResult`/`DeliveryError`, and the `SimulatedDeliveryClient` mock.
- `backend/app/domain/delivery/adapters.py` — the real `webhook`/`email` transports and the ENV-selected `build_delivery_client` factory (with mock fallback).
- `backend/app/domain/delivery/service.py` — the exactly-once delivery logic run by the worker (probe-before-retry, park-on-ambiguous).
- `backend/app/domain/delivery/message.py` — one neutral, provider-agnostic rendering of a request so the admin preview matches what a real destination would receive.
- `backend/app/domain/jobs/tasks.py` — `run_reconcile_deliveries`, the periodic sweep that rescues requests orphaned by a crashed/lost delivery job.

## Interfaces
- **Public endpoint:** `POST /api/v1/requests` — submit a `strategy_call`, `portal_support`, or `human_escalation`; returns a local `request_id`, `status`, `reference`, and a `duplicate` flag (invariant #6).
- **Worker jobs:** `deliver_request` (on-demand, enqueued per fresh request) and `delivery_reconcile` (periodic, parks/re-enqueues orphans).
- **Admin screens:** `GET /admin/requests` (filter by type/status; contact email masked; shows `destination`, `delivery_channel`, `external_reference`, `last_delivery_error`) and `POST /admin/requests/{id}/redeliver` (admin-only, audited, resets a parked request and re-enqueues it). The dead-letter / delivery-failure counts feed the admin monitoring alerts.
- **Model tools:** none — the read-only model can search and answer but never touches this path.

## Status & limitations
- **Live on staging** via the `simulated` transport: it records exactly what *would* be sent (visible in admin) and needs no credentials, so the whole receive → deliver → delivered pipeline runs for real against a mock destination.
- **`enable_delivery` is a dark-launch flag** (defaults off): when off, requests are still captured and confirmed but no delivery job is enqueued.
- **Real destinations aren't wired yet.** The `_DESTINATION` map (strategy call → CRM, support/escalation → ticketing) uses placeholder labels (`hubspot`/`zendesk`) pending the owner decision on actual systems (doc 06 §6). Switching on a webhook or email transport is a config + credentials change, not a code change; a misconfigured transport safely falls back to the mock.
- **Un-dedupable channels trade retries for safety.** Webhook/SMTP `find_by_reference` always reports "unknown," so post-send failures are parked for a human rather than risking a duplicate. A destination that *can* dedupe would be probed before any retry.

## Future & scaling
- **Stand up a real transport.** The lowest-lift first destination is a Slack/Teams incoming webhook or a shared team inbox — both already implemented; they just need URLs/credentials and the ENV flip.
- **A queryable CRM/ticketing adapter** (e.g. HubSpot/Zendesk) could implement a real `find_by_reference`, upgrading ambiguous post-send failures from "park for admin" to a safe automatic retry — the delivery service already probes on retry when the client supports it.
- **Richer routing.** `_DESTINATION` is a static per-type map today; per-region or per-industry routing could hang off the already-captured `fields` without touching the delivery mechanics.
- **Operational surface.** Parked requests already show `last_delivery_error` and a one-click audited redeliver; a natural extension is surfacing delivery latency and per-channel success rates in the admin insights, since the timestamps and `delivery_channel` are already stored.

## Related
- [canonical answers](canonical-answers.md) — sensitive topics answer from canonical content; a portal or escalation ask is what routes a visitor into this write path.
- [background worker & jobs](worker-and-jobs.md) — the durable job model, atomic claim, retry/dead-letter engine this delivery rides on.
- [admin console](admin-roles-and-audit.md) — the requests queue, masked PII, audited reveal/redeliver, and monitoring alerts.
- [retention & privacy](privacy-and-retention.md) — how request PII is redacted on subject erasure and swept by retention class.
- Architecture: [doc 03 ADR-019 / ADR-016 / ADR-011](../03_Architecture_and_Decision_Records.md). Contracts: [doc 04 §7–8](../04_API_and_Data_Contracts.md).
