# Canonical answers & the approval lifecycle

> **In one line:** A small library of approved, must-win answers for Cadre's sensitive topics (pricing, security, the client portal, case studies, the AI Maturity Index deferral, and more) that override anything the model would otherwise generate.

**Status:** Live on staging  ·  **Introduced:** POC core; draft→approved lifecycle added in V1

## What it is
Canonical answers are pre-written, human-owned responses stored in MongoDB, one per sensitive **intent** (e.g. `pricing`, `data_security`, `case_study`). When a visitor asks about one of these topics, the model does not compose an answer from memory — it fetches the approved wording and delivers it. Each record also carries an owner, a review date, an optional escalation flag, and a list of follow-up actions the app may offer (like "Book a strategy call"). This is CLAUDE.md **invariant #8**: for these topics, canonical answers win.

## Why it exists
The bot is public-facing and speaks for an AI consultancy, so a hallucinated price, an invented certification, or a leaked client name is a real business and legal risk. Canonical answers move the wording for exactly those high-stakes topics out of the model's discretion and into content that a named owner has reviewed and approved. This is the decision recorded in [ADR-008](../03_Architecture_and_Decision_Records.md) ("Canonical answers for sensitive subjects"). V1 added the lifecycle around it: content is drafted, then explicitly approved before it is ever served, and it is promoted from staging rather than edited live (invariant #14).

## How it works
- The model has a read-only tool, `get_canonical_answer(intent)`, and is instructed to always call it for the sensitive topics. It never writes or invents these answers (invariant #2).
- The repository returns **only `approved` records**. A draft — or no record — comes back as "no match," so the model falls back to retrieval or escalation instead of exposing unreviewed wording.
- The tool result is stored on the assistant message (`canonical_answer_id`) and carries `allowed_action_ids`. The application — not the model — resolves those IDs into `{id, label}` buttons via a fixed allowlist; IDs the model invents are never trusted for behavior ([ADR-016](../03_Architecture_and_Decision_Records.md)).
- The client portal answer keeps a `[PORTAL URL]` placeholder; the real URL is not stored in the content — a separate `get_portal_information` tool returns it from config and the model composes it into the reply, so the URL lives in configuration, not in content.

See [doc 04 §5](../04_API_and_Data_Contracts.md) for the tool contract and [doc 05 §3](../05_Conversation_and_Content_Specification.md) for the approved wording.

## Key files
- `backend/app/domain/canonical/models.py` — the `CanonicalAnswer` document (intent, content, owner, status, `allowed_action_ids`, `mandatory_escalation`, review date) and the `CanonicalMatch` tool result.
- `backend/app/domain/canonical/repository.py` — read path (`get_canonical_answer`, approved-only), idempotent `upsert` keyed by intent, and `approve` (draft → approved).
- `backend/app/agent/tools.py` — the `get_canonical_answer` and `get_portal_information` tool specs and their execution; the intent list the model chooses from.
- `backend/app/agent/actions.py` — the application-owned action-label allowlist that turns action IDs into safe follow-up buttons.
- `backend/app/agent/orchestrator.py` — wires the tool result onto the assistant message and records unanswerable questions (see below).
- `backend/scripts/seed_canonical.py` — the verbatim approved wording (from doc 05 §3) and the seeding command.
- `backend/app/api/admin/router.py` — admin endpoints to list and approve canonical answers.

## Interfaces
- **Model tools:** `get_canonical_answer(intent)`, `get_portal_information()` — read-only.
- **Intents currently covered:** `company_overview`, `service_overview`, `industry_fit`, `ai_maturity_index`, `llm_selection`, `data_security`, `pricing`, `case_study`, `portal_access`, `strategy_call`, and `unsupported`.
- **Offered actions (allowlist):** `strategy_call`, `service_discovery`, `portal_access`, `portal_support`, `human_escalation`, plus topic shortcuts. These render as one-tap buttons; the actual request only happens when the user confirms (a browser-side write, never the model).
- **Admin screens/endpoints:** `GET /api/v1/admin/canonical` (lists every answer with intent, name, status, owner, review date) and `POST /api/v1/admin/canonical/{intent}/approve` (promote a draft — **admin role only, and audited**).
- **Seeding (dev/ops):** `uv run python scripts/seed_canonical.py` (writes approved baseline) or `--status draft` to stage content pending approval.

## Status & limitations
- **Live on staging.** Eleven canonical answers are seeded and served, with wording taken verbatim from doc 05 §3. Owners and 180-day review dates are attached per record.
- **Only one topic is force-flagged for escalation.** `data_security` carries `mandatory_escalation=True` (certifications, compliance, residency, and client-specific architecture must go to a human). That flag is surfaced to the model to signal it must offer escalation and the answer offers `human_escalation`; it is guidance to the model plus the offered action, not a hard code-level block.
- **Approve is a status flip, not full versioning.** A record's `status` is set once on insert and only ever changed via `approve()`; re-seeding never downgrades an already-approved answer, so a re-seed can't silently disable the live baseline. `version` exists on the model but there is no multi-version history or rollback yet.
- **Unsupported questions are captured.** When the model routes to `unsupported`, the orchestrator records the visitor's verbatim question to the admin unresolved list, so gaps in coverage surface for owners to write new canonical content.
- **Adjacent, in progress:** an insights/gaps engine can auto-draft proposed canonical answers that flow through this same draft→approved gate — treat that as in-progress tooling, not a shipped capability here.

## Future & scaling
- **True content versioning.** The `version` field is present but unused; a natural next step is keeping prior approved versions for audit and one-click rollback, rather than in-place status flips.
- **Review-date workflow.** Review dates are stored but nothing acts on them yet; a scheduled worker job could flag answers past review for their owners.
- **Broader coverage from the unresolved list.** The captured unsupported questions are a ready backlog for new intents; a lightweight admin flow from "unresolved question" to "draft canonical answer" would close that loop.
- **Golden-set gating on content edits.** Because these answers are safety-critical, any change to canonical wording should pass the golden evaluation set before promotion (per CLAUDE.md content rules) — worth wiring into the promotion path as content volume grows.

## Related
- [Read-only model tools & actions](chat-and-turn-loop.md) · [Knowledge search & retrieval](knowledge-retrieval.md) · [Admin audit & PII reveals](admin-roles-and-audit.md)
- Architecture: [ADR-008](../03_Architecture_and_Decision_Records.md) (canonical answers), [ADR-016](../03_Architecture_and_Decision_Records.md) (structured client actions)
- Contracts: [doc 04 §5](../04_API_and_Data_Contracts.md) (tool contract), [doc 04 §7–8](../04_API_and_Data_Contracts.md) (canonical document + index)
- Content: [doc 05 §3](../05_Conversation_and_Content_Specification.md) (approved wording & escalation rules)
