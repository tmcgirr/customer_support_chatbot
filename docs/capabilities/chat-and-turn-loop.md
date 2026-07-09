# Public chat & the turn loop

> **In one line:** The end-to-end visitor conversation — an embedded chat widget that creates a conversation, streams the assistant's reply token-by-token, and drives one atomic, read-only "turn" per message through MongoDB and the OpenAI Responses API.

**Status:** Live on staging  ·  **Introduced:** POC (hardened in V1)

## What it is
This is the core product surface: the chat a website visitor actually uses. A visitor opens the widget, gets a short welcome plus a few suggested chips, types a question, and watches the answer stream in. Under the hood each message is a "turn" — a single, tightly bounded unit of work that appends the user's message, calls the model with the conversation so far, lets the model consult three read-only tools, streams the reply, and persists the result. Everything a PM thinks of as "the bot answering" is one pass through this loop.

## Why it exists
The bot has to be safe, cheap to reason about, and impossible to corrupt through double-clicks, flaky networks, or a slow model. The team chose a deliberately simple design: MongoDB is the single source of truth for history and every model call is stateless (no provider-side conversation object), so deletion, retention, and debugging are one-store operations ([ADR-014](../03_Architecture_and_Decision_Records.md)). A whole turn — run lock + user-message append + duplicate check + message cap — is enforced in **one atomic MongoDB `findOneAndUpdate`**, so concurrency is decided by the database rather than by application locking ([ADR-015](../03_Architecture_and_Decision_Records.md), [doc 03 §3.1](../03_Architecture_and_Decision_Records.md)). The model is kept **read-only** on purpose: its only powers are to look things up, never to send or write, so a jailbreak can't take a business action.

## How it works
- **Create.** `POST /api/v1/conversations` inserts a conversation document and returns a stateless HMAC session token plus the welcome text and suggested actions. No session collection — the token is self-verifying ([invariant #9](../../CLAUDE.md)).
- **Begin a turn (atomic).** `POST …/messages` calls `begin_turn`, whose single `findOneAndUpdate` filter simultaneously requires: the conversation exists, no run is active, this `client_message_id` is new, and the message cap (default 40 user turns) isn't reached. Exactly one caller can match; everyone else is diagnosed into `DUPLICATE`, `BUSY`, or `CAP_REACHED`.
- **Build the window & call the model.** The orchestrator rebuilds the model's context purely from the completed messages in the Mongo document, loads the versioned system prompt, and calls the OpenAI Responses API through the adapter with `store=False`. The call is stateless — the full window is resent every round.
- **Tool loop.** The model may call the three read-only tools ([search_knowledge](knowledge-retrieval.md), [get_canonical_answer](canonical-answers.md), get_portal_information). The app executes them in-process and resends the transcript, up to a bounded number of rounds; on the final round the tools are withheld so the model must emit a text answer.
- **Stream.** Text deltas are pushed to the widget as Server-Sent Events (`message.accepted` → `response.started` → `response.delta`* → `response.completed` | `response.failed` | `limit.reached`). A live turn heartbeats its run lock so a slow answer is never mistaken for a leaked one.
- **Persist & unlock.** On completion or failure the assistant message (content, sources, usage, latency, `canonical_answer_id`, trace metadata, any error code) is appended and the lock is cleared — on every exit path, so a dropped turn can never brick a conversation at `BUSY`.

See [doc 04 §3](../04_API_and_Data_Contracts.md) for the exact request/response and event contracts.

## Key files
- `backend/app/api/public/conversations.py` — create-conversation endpoint; welcome text + suggested-action chips; mints the session token.
- `backend/app/api/public/messages.py` — send-message (SSE) and get-transcript endpoints; per-session and per-IP rate limits before the paid model path.
- `backend/app/api/sse.py` — SSE framing helpers and anti-buffering headers that keep deltas from being coalesced by proxies.
- `backend/app/agent/orchestrator.py` — the turn loop itself: begin → window → model/tool rounds → complete/fail, emitting transport-agnostic stream events.
- `backend/app/agent/adapter.py` — the **only** place OpenAI is called; normalizes events/usage/errors and does one-time fallback-model retry (nothing OpenAI-typed escapes here).
- `backend/app/agent/tools.py` — the three read-only tool specs and their in-process execution.
- `backend/app/agent/prompt.py` — versioned system-prompt loader (`CURRENT_PROMPT_VERSION`).
- `backend/app/domain/conversations/{models,repository}.py` — the embedded-message conversation document and the atomic `begin_turn` / `complete_turn` / lock operations.
- `frontend/src/conversation/useConversation.ts` — the widget's conversation state machine: streaming, reconnect, drop-reconcile, retry, idempotent client message IDs.
- `frontend/src/shell/WidgetFrame.tsx` — the launcher + panel chrome, focus trapping, and host resize notifications.
- `frontend/src/host/messaging.ts` — origin-checked `postMessage` bridge between the iframe widget and the host page.
- `frontend/src/api/client.ts` — the sole backend caller; POST + streaming reader parses SSE frames (EventSource can't POST).

## Interfaces
- **Endpoints:** `POST /api/v1/conversations`, `POST /api/v1/conversations/{id}/messages` (SSE), `GET /api/v1/conversations/{id}/messages` (transcript for reconnect).
- **Model tools (read-only):** `search_knowledge`, `get_canonical_answer`, `get_portal_information`.
- **SSE events:** `message.accepted`, `response.started`, `response.delta`, `response.completed`, `response.failed`, `limit.reached`.
- **Widget surfaces:** floating launcher, chat panel, welcome chips, composer, error/reconnect banner. Admin screens are out of scope here.

## Status & limitations
- **Live on staging** end-to-end against the real Responses API. SSE is verified through the actual DigitalOcean routing path (a POC gate that anti-buffering headers protect).
- **Reconnect is real and defensive.** The session (conversation id + token) is mirrored to per-tab `sessionStorage`, so a reload resumes from the transcript instead of starting over. If a stream drops without a terminal event, the widget re-fetches the transcript and only marks the turn failed if no *new* completed assistant message actually landed — the answer often survives a lost frame. A `401` (expired token) recovers by offering a fresh chat.
- **Degraded states are explicit:** `creating`, `reconnecting`, `streaming`, `error`, plus copy for busy, message-too-long, cap-reached, and general model-failure — each with the appropriate recovery action (retry / reconnect / start-new).
- **Stale-lock recovery** is opportunistic: a leaked lock older than the stale window is released and the turn retried once, so a crashed process can't strand a conversation at `CONVERSATION_BUSY`.
- **Citations are dark-launched OFF.** The stored assistant message retains its approved `sources`, but public display is gated behind a settings flag that is off pending a Product/Marketing decision — while it is off the `response.completed` event carries no citation payload, and the `response.citation` / `action.offered` frames named in [doc 04 §3.2](../04_API_and_Data_Contracts.md) are not emitted as separate events.
- **Not yet in production.** Production stand-up is gated on owner/infra decisions, not on this code.

## Future & scaling
- **Context window at scale.** Today the whole capped transcript fits the model window with no summarization ([doc 03 §3.1](../03_Architecture_and_Decision_Records.md)). If caps rise or answers grow, add windowing/summarization at `_build_window` without touching the storage model.
- **More API instances.** Because turns are atomic on one document and the model call is stateless, the send path scales horizontally with no shared in-process state; the documented scaling sequence is indexes → production cluster → worker → more API instances ([doc 03 §7](../03_Architecture_and_Decision_Records.md)).
- **Provider portability.** Swapping or adding a model provider is a change to `adapter.py` alone — the orchestrator never sees an OpenAI type — which keeps the fallback-model story and any future provider mix contained.
- **Turning citations on** is a config flip plus golden-set validation, not new plumbing.
- **Human takeover** (live agent joining a conversation over WebSockets) is explicitly V2, not part of this loop.

## Related
- [Canonical answers](canonical-answers.md) — the approved-answer path the `get_canonical_answer` tool serves.
- [Knowledge search](knowledge-retrieval.md) — the retrieval behind `search_knowledge`.
- [Requests & delivery](request-delivery.md) — the only place a real side effect happens (browser-submitted, worker-delivered), never the model.
- Architecture: [doc 03 §3.1 turn loop](../03_Architecture_and_Decision_Records.md), ADR-014/015/016. Contracts: [doc 04 §3](../04_API_and_Data_Contracts.md). Invariants: [CLAUDE.md](../../CLAUDE.md) #1 (Mongo source of truth), #2 (read-only model), #3 (one atomic turn), #9 (stateless session token).
