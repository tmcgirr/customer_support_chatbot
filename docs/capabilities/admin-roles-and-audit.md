# Admin console: roles, masking & audit

> **In one line:** The internal operator console for the support bot — two roles (`admin` vs `viewer`), PII masked by default in every view, and an append-only audit trail behind every reveal, approval, and delivery action.

**Status:** Live on staging  ·  **Introduced:** V1

## What it is
A separate single-page app (served at `admin.html`, distinct from the public widget) where Cadre staff monitor conversations, review submitted requests, manage content and knowledge, and run data-lifecycle actions. It is built around a strict privacy posture: operators see **masked** contact details and transcripts by default, and any action that unmasks personal data or changes what the bot serves is role-gated and **audited**. This is the human oversight layer for a bot that is otherwise fully automated and read-only.

## Why it exists
The bot handles unauthenticated public visitors who may type emails, phone numbers, and company details into chat. Someone at Cadre needs to triage those conversations, approve content, and act on delivery failures and privacy requests — but that operational access is itself a privacy risk. V1 answers it with least-privilege: read access is broad (a `viewer` can see masked data), while unmasking or mutating is narrow (`admin` only) and never silent. Every privileged act leaves a who/what/why record. This satisfies invariant #12 (role-controlled admin, masking by default, audited reveal/export) and doc 03's V1 note that "admin access adds roles, reveal-with-reason, and audit" (doc 03 §"Admin access").

## How it works
- **Two roles.** `require_admin` authenticates either role for read routes; `require_admin_role` additionally requires `admin` for any write/reveal/approve route — a `viewer` who tries is authenticated but `403`'d, not `401`'d. The SPA calls `GET /api/v1/admin/me` on login to learn its role and hide admin-only buttons.
- **Masking is the default.** Free-text admin fields pass through `mask_pii_in_text` (emails → `a***@acme.com`, phone runs → `***-***-NN`) and contact emails through `mask_email` at **read** time, so the verbatim value stays on record for a later audited reveal. This covers transcripts, model summaries/key points, unresolved questions, insights cluster text, and request/privacy contact emails.
- **Reveal / mutate is audited.** `POST …/reveal` (request or conversation) returns unmasked data but requires a non-empty `reason` and writes an `AuditRecord`. The same reason-required + audit-first pattern guards `redeliver`, `approve_canonical`, knowledge upload/approve/remove/replace, and privacy-request `verify` — for these the audit write happens **before** the side effect, so a failed audit can't leave an un-audited action. (The manual insights *Run now* is also audited, but it is admin-only and takes no operator reason.)
- **Append-only trail.** `AuditRepository.record` inserts one immutable row (actor, role, action, local `target_type`/`target_id`, masked reason, timestamp); records are never updated or deleted. `GET …/audit` renders the trail in the Audit screen.
- See [doc 04 §4 (Admin APIs)](../04_API_and_Data_Contracts.md) and [doc 04 §10 (PII Contract)](../04_API_and_Data_Contracts.md) for the contract.

## Key files
- `backend/app/api/admin/auth.py` — role model: `AdminPrincipal`, `require_admin` (read) and `require_admin_role` (admin-only), constant-time credential check.
- `backend/app/api/admin/router.py` — all admin endpoints; applies masking on reads and calls the audit repo on privileged writes.
- `backend/app/core/masking.py` — `mask_email`, `mask_pii_in_text` (emails + phones); masking applied at read time.
- `backend/app/domain/audit/models.py` — `AuditRecord` + the closed `AuditAction` enum (reveal, redeliver, approvals, knowledge ops, privacy verify, export, delete).
- `backend/app/domain/audit/repository.py` — insert-only writer + `list_recent`; masks any PII in the operator's reason before storing.
- `backend/app/core/security.py` — stateless HMAC session tokens for the *public* visitor session (invariant #9); not the admin login (see limitations).
- `frontend/src/admin/AdminApp.tsx` — SPA shell, login, tab nav; passes `role` to views so admin-only actions are hidden for viewers.
- `frontend/src/admin/api.ts` — admin API client; creds + identity held in memory only, never `localStorage`.
- `frontend/src/admin/Audit.tsx` — renders the audit trail; sibling views: `Conversations`, `ConversationDetail`, `Requests`, `Canonical`, `KnowledgeSources`, `Privacy`, `Insights`, `Funnel`, `Unresolved`, `Dashboard`.

## Interfaces
Admin screens (tabs in the SPA): **Dashboard**, **Insights**, **Funnel**, **Conversations** (+ detail), **Requests**, **Knowledge**, **Canonical**, **Unresolved**, **Audit**, **Privacy**.

Representative endpoints under `/api/v1/admin` (all auth-gated):
- Read (either role): `GET /me`, `/dashboard`, `/conversations[/{id}]`, `/requests`, `/unresolved-questions`, `/canonical`, `/knowledge-sources`, `/privacy-requests`, `/audit`, `/monitoring`, `/system`.
- Admin-only + reason + audit: `POST /requests/{id}/reveal`, `/conversations/{id}/reveal`, `/requests/{id}/redeliver`, `/canonical/{intent}/approve`, `/knowledge-sources[…]` (upload/approve/remove/replace), `/privacy-requests/{id}/verify`.
- Admin-only + audited (no operator reason): `POST /insights/run`.

## Status & limitations
- **Live on staging.** Roles, default masking, reason-required reveals, and the append-only audit trail all work end-to-end.
- **Admin login is a dev stub.** `auth.py` authenticates via HTTP Basic against two config credential pairs (`admin` / `viewer`) and assumes HTTPS in front. The docstring is explicit that a real identity provider (OIDC/SAML) replaces `require_admin`'s body in production. Do **not** conflate this with invariant #9's stateless HMAC token — that secures the public visitor session (`app/core/security.py`), not the admin console.
- **Masking is best-effort regex.** `mask_pii_in_text` catches emails and phone-shaped digit runs; other PII forms (names, addresses) in free text are not masked. Reveal is still the audited escape hatch for the verbatim value.
- **Audit is retained but not exposed for export.** `AuditAction` includes `export`, but the trail is currently only listed via `GET /audit` (capped at 100, newest first) with no pagination or download.

## Future & scaling
- **Swap the auth stub for the production IdP** (OIDC/SAML) by replacing `require_admin`'s body — the role model, dependencies, and every downstream check already assume a resolved `AdminPrincipal`, so nothing above `auth.py` changes. This is a V1-gate/owner decision, not new engineering.
- **Audit at scale:** the `AuditRecord` id is a ULID and the collection is indexed on `at` and `(target_type, target_id)`, so per-target history and cursor pagination are cheap to add; a signed/exportable audit report would round out compliance evidence.
- **Finer roles / tenancy** (per-tenant scoping, `client_role`) are explicitly a V2 concern (doc 04 §11); the current binary model is deliberate for V1's single-tenant, staff-only surface.
- **Richer masking** (name/address detection) would reduce reliance on reveal, trading recall for more false positives — worth it only if reveal volume in the audit trail shows operators unmasking routinely.

## Related
- [Canonical answers](canonical-answers.md) — approval lifecycle gated in this console.
- [PII masking & data lifecycle](privacy-and-retention.md) — privacy-request verification and retention share the audit trail.
- [External delivery worker](request-delivery.md) — the redeliver action re-enqueues a parked delivery job.
- [doc 03 §"Admin access"](../03_Architecture_and_Decision_Records.md) · [doc 04 §4 Admin APIs](../04_API_and_Data_Contracts.md) · [doc 04 §10 PII Contract](../04_API_and_Data_Contracts.md) · invariants #5 (no PII in logs), #9 (stateless HMAC session), #12 (roles + audit).
