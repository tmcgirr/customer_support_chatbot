# Privacy Notice — Cadre AI Support Chatbot

> **STATUS: DRAFT — pending Legal/Privacy sign-off** (doc 06 §6, Legal/Privacy owner).
> This notice is written to **match the system's actual data handling** (Phase V6). It is
> the engineering description of behavior; Legal owns the final customer-facing wording and
> the confirmed retention periods. If Legal changes a period, update `app/core/config.py`
> **and** this file together — the golden rule is that the two never diverge. Current
> versions: chat disclosure `privacy-2026-07`, contact consent `consent-2026-07`
> (`chat_disclosure_version` / `contact_consent_version` in config).

## What we collect

- **Conversation transcripts.** Messages you send the assistant and its replies, plus
  technical metadata (entry page, locale, timestamps, which prompt/model answered). The
  assistant is read-only and takes no action on your behalf.
- **Contact & request details** — only when you explicitly submit a form (book a strategy
  call, portal support, or connect with a person): name, email, optional company, and the
  fields for that request. Recorded with the consent version shown at submission.
- **Feedback** — an optional rating (and optional comment) on an answer.

We do **not** ask for credentials, and the assistant never confirms whether you are a client.

## The chat disclosure & consent

- On opening the widget you are shown the **chat disclosure** (version `privacy-2026-07`),
  recorded on the conversation.
- Submitting any contact form records your **consent** (version `consent-2026-07`) with the
  request. Drafts are never stored server-side; only a confirmed submission is persisted.

## How long we keep it (retention)

Enforced automatically by a daily background **retention sweep** plus a database TTL — no
manual deletion is on the request path. Periods (config defaults, **pending Legal
confirmation**):

| Data | Retention | Mechanism |
|---|---|---|
| Abandoned **anonymous** conversations (walked away, no request submitted) | **30 days** from last activity | TTL index auto-purge (`expire_at`), stamped when the conversation is marked abandoned |
| Any conversation (hard backstop) | **365 days** from last activity | retention sweep, hard delete |
| Request records (contain contact PII) | **365 days** from creation | retention sweep, hard delete |
| Feedback | **365 days** from creation | retention sweep, hard delete |
| Privacy-request records (erasure/access proof) | **730 days** | retention sweep, hard delete |

Aggregate counts are snapshotted daily before data expires, so retention deletion does not
distort historical metrics. A conversation that led to a request is **not** given the short
anonymous TTL — it is retained with its request's lifecycle.

## Your rights — access & deletion

Submit a request at **`POST /api/v1/privacy/requests`** with `{ type: "access" | "deletion",
email, conversation_id? }` (also surfaced via the support widget / a privacy page). This
endpoint is unauthenticated and returns the **same acknowledgement to everyone** — it never
reveals whether we hold any data about you.

1. **Verification.** We verify your identity out of band before acting. No deletion happens
   from the public request itself.
2. **Deletion.** Once an operator verifies your request, a background job **erases your data
   across every store**: your conversations and requests are redacted to tombstones (message
   content, contact details, and free-text fields removed; a minimal non-personal record is
   kept as proof the erasure occurred) and your feedback is deleted. Scope = every request
   bearing your (verified) email and those requests' conversations. A conversation you name
   that we cannot link to your verified email (e.g. an anonymous chat where you submitted no
   request) is **not** auto-deleted — an operator handles it after confirming it is yours, so
   one person can never trigger deletion of another's transcript. The erasure is recorded in
   an append-only audit trail (no personal data in the trail itself).
3. **Access.** A verified access request is fulfilled by an operator providing your recorded
   data through the audited admin path.

## Processors & provider retention

We use OpenAI to generate responses. Conversation history is stored **only in our database**;
model calls are **stateless** (`store=false`) and we never create provider-side conversation
objects — the provider does not retain your conversation as a business record. The provider
may keep transient operational logs under its own terms; those are outside our single-store
deletion and are documented here rather than deleted by us.

## Logs & security

Application logs contain **local identifiers and counts only** — never message content,
contact details, or any personal data. Access to unmasked data is limited to authorized
operators and every access is audited.
