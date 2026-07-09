# Security Review & Production Readiness — V1 (Cadre AI Support Chatbot)

**Status:** Current security posture and production plan
**Last reviewed:** 2026-07-09
**Scope:** the full V1 attack surface — public chat / LLM boundary, abuse & cost controls, input
handling, admin portal, delivery worker, frontend widget, transport / secrets / config.
**Method:** subsystem code review across each surface, with every consequential finding
independently re-verified against the code and scored by real exploitability in a public,
single-tenant, anonymous-visitor deployment. Severities below are those verified assessments.

---

## 1. Verdict

The V1 build has a **well-designed trust boundary** and a solid set of app-level controls, but it
is **not yet cleared for public internet traffic.** Two prerequisites — both infrastructure /
decisions rather than code — gate the launch:

1. **An edge CDN / WAF** in front of the app for volumetric protection, edge rate limiting, and
   bot mitigation. The app enforces per-session / per-IP abuse caps on every expensive path as
   defense-in-depth, but volumetric floods, rotating-IP abuse, and automated bots need the edge.
2. **A production identity provider (OIDC/SAML)** for the admin portal. Admin currently
   authenticates with a single shared HTTP Basic credential, so the audit trail cannot attribute
   who revealed PII or ran a deletion, and there is no MFA.

**The reassuring half:** the thing people fear most about "a live LLM" — prompt injection,
jailbreaks, exfiltration through the model — is the **strongest** part of this build. The model is
read-only, side effects are browser-driven (never model-driven), provider IDs/errors never leak,
and only human-approved canonical content is served. A prompt-injection attacker cannot exfiltrate
data, trigger a write, or reach another user. **The residual risk is ordinary web-app abuse control
and admin auth, not the AI.**

Mapping to the V1 public gate (doc 02 §8): the open items are **role-controlled admin with a real
IdP** and **edge abuse controls**; everything else in the gate is met or is a content/legal
sign-off. Those two are the launch blockers.

---

## 2. What is being defended (architecture)

- **FastAPI modular monolith** on DigitalOcean; REST + SSE. MongoDB is the single source of truth
  (conversation history is embedded messages). Stateless model calls via a thin OpenAI Responses
  adapter — no server-side provider conversation object.
- **Trust boundary (load-bearing):** the model has three **read-only** tools (`search_knowledge`,
  `get_canonical_answer`, `get_portal_information`) and is *not in the write path*. Side effects go
  through `POST /api/v1/requests` (browser, after user confirmation) and the delivery worker.
  Suggested actions are IDs from an app allowlist, not model free-text.
- **Public auth:** stateless HMAC session token (24h), Bearer header, bound to the conversation ID.
  No session store.
- **Admin:** separate router, masked PII by default, two roles (admin / viewer), reveal-with-reason
  + append-only audit.
- **V2 (out of scope — a separate trust tier):** authenticated clients, tenancy, per-tenant
  retention, private Vector Stores, client tools with per-call tenant/role validation, human
  takeover. None of V1's anonymous-visitor model changes here — V2 opens a *new* boundary (§8).

---

## 3. Controls in place (verified — the security baseline)

**Model / LLM boundary**
- Only three read-only `ToolSpec`s exist; no write/send/submit tool anywhere. Suggested actions come
  from tool-result `allowed_action_ids`, never parsed from model text. `store=False` on every call.
- Cross-user isolation intact (the window is built from one conversation; tools hit only shared
  public stores). No path exposes another user's data or any internal/provider ID.
- Only `status="approved"` canonical records are served; re-seed can't downgrade an approved record.
- Every model call is bounded by a per-response output-token ceiling (`openai_max_output_tokens`),
  a 5-round tool cap, and the 40-message conversation cap.

**No XSS**
- Repo-wide: no `dangerouslySetInnerHTML`, no `innerHTML`, no markdown-to-HTML renderer. Model/user
  text renders as escaped JSX text in both widget and admin.

**Abuse & cost controls (app-level, defense-in-depth under the future edge)**
- Per-session **and** per-IP throttle on `send_message` (the paid LLM path) and per-conversation +
  per-IP throttle on `submit_request` (external delivery), returning `RATE_LIMIT`; per-IP cap on
  conversation-create and privacy-request. Caps in `core/config.py`.
- `client_ip()` derives the client from the **rightmost trusted proxy hop** (`trusted_proxy_hops`),
  so a spoofed leftmost `X-Forwarded-For` cannot defeat the per-IP caps.
- Atomic single-document turn (lock + append + dedupe + cap); idempotency on messages
  (`client_message_id`) and requests (`Idempotency-Key`). Public string fields are length-bounded.

**Admin authorization**
- All 27 admin routes are guarded; reads take admin-or-viewer, mutations/reveals take admin-only
  (viewer → 403). Every reveal/verify/approve validates → audits (with a required reason) → acts. No
  missing-guard route, no second admin router. `contact_company` is masked in list views (full value
  only via the audited reveal, like email).

**Transport / secrets / config**
- Fail-closed config (`core/config.py` is the only env reader): non-dev refuses placeholder/empty
  secrets, a sub-16-char admin/viewer or session secret, localhost Mongo, and wildcard/localhost/
  non-https CORS. Secrets are `SecretStr`; none are committed. Interactive docs/OpenAPI are disabled
  outside dev.
- Security headers on **both** staging and prod Caddy (HSTS, nosniff, referrer, permissions,
  `X-Frame-Options: DENY` on `/admin.html`, and a Content-Security-Policy).
- Log hygiene (invariant 5): static AST scan + runtime formatter guard; events reference IDs only —
  no PII, tokens, or provider messages, including on the worker/delivery/error paths.

**Delivery worker / data lifecycle**
- Bounded retries → dead-letter → reconciliation; poison-pill jobs dead-letter; one bad job can't
  wedge the loop. Provider libraries/types/errors never leave the adapter. SMTP `STARTTLS` verifies
  the relay certificate + hostname. No user-driven SSRF (destinations are config-only).
- Privacy erasure refuses the unauthenticated `conversation_id` and scopes deletion to the
  **verified** requester email, so a verified requester can't erase someone else's transcript.

**Frontend widget**
- Host-side loader is origin-pinned; the token is sent as a Bearer header (never in a URL). The
  widget fails closed on wildcard `postMessage` origins in a production build.

---

## 4. Open risks (current)

Ranked by verified severity. These are what remains — the §3 controls are assumed in place.

| # | Risk | Sev | Category | Where / note |
|---|------|-----|----------|--------------|
| R1 | Admin portal authenticates with a **shared HTTP Basic credential**, not the IdP → the audit actor is always the same username (no per-user attribution of PII reveals / deletions), no MFA, no login lockout. A ≥16-char password floor is enforced as a stopgap. | **High** | Admin auth | `api/admin/auth.py`; fixed by §5 item 2 |
| R2 | **No edge WAF / CDN / bot mitigation.** App per-IP + per-session caps blunt single-source abuse, but volumetric floods, rotating-IP abuse, and headless bots face no friction above them. | **High** (gating) | Abuse | edge layer; §5 items 1, 3 |
| R3 | Audit trail is append-only **by convention only** — no hash-chain/WORM, and the single app Mongo role can update/delete the `audit` collection. | Med | Admin | `domain/audit/repository.py` |
| R4 | No **global OpenAI spend circuit-breaker**, and no per-turn wall-clock timeout / concurrent-stream ceiling on the request path. | Med | Abuse/cost | orchestrator / worker; pairs with alerting |
| R5 | The widget document sets **no `frame-ancestors` allowlist** — a malicious page can frame it and attempt clickjacking of the consent/PII form (app-level messaging already fails closed). | Low–Med | Frontend | widget CSP per embedder |
| R6 | Widget session token is persisted to `sessionStorage`, contradicting the stated in-memory invariant (anonymous, short-lived, conversation-scoped token — bounded impact). | Low | Frontend | `conversation/useConversation.ts` |
| R7 | At-most-once delivery breaks in a narrow worker-crash window (send returns → crash → re-send); **not attacker-controllable**. | Low | Delivery | `domain/delivery/service.py` |
| R8 | Feedback endpoint is unthrottled + reads the full transcript; free text isn't unicode/control-char normalized. | Low | Input | `api/public/feedback.py` |
| R9 | The CSP is present and safe for the current build (all scripts are external assets) but has **not yet been browser-verified** on the deployed environment. | Low (operational) | Transport | verify at staging before cutover |

**Not a V1 risk (V2):** admin routes are single-tenant by design — any admin/viewer sees all data,
and ID-parameterized routes have no object-scope check. Correct today; becomes a cross-tenant IDOR
surface the moment authenticated clients / tenancy arrive (§8).

---

## 5. Planned for production (the launch gate)

These turn "hardened baseline" into "safe for public traffic." Most infra items are named in doc 06
§6 with owners — this review treats items 1–2 as **hard gates**, not nice-to-haves.

### 5a. Infrastructure / decisions
1. **CDN / WAF in front (Cloudflare or DO)** — volumetric protection, edge rate limiting, bot
   mitigation. On cutover set `trusted_proxy_hops=2` so client-IP derivation peels the CDN hop too.
   **Hard prerequisite — Engineering (provider decision). Resolves R2.**
2. **Production identity provider (OIDC/SAML)** for admin — per-user accounts (real audit
   attribution), MFA, revocation; the seam is `api/admin/auth.py::require_admin`. **Engineering/IT.
   Resolves R1.**
3. **Bot mitigation on conversation-create** (Turnstile / hCaptcha / proof-of-work). **Resolves R2.**
4. **Secrets manager** (inject secrets, not a file on disk) + a rotation runbook.
5. **Alerting wired** (V1 exit item 8): page on delivery dead-letters, **OpenAI spend spikes**,
   conversation-creation-rate spikes, and admin-login failures.
6. **Content sign-off + retention periods** (Legal / Marketing / Sales / Security) — content safety
   (no prices/certs/client-confirmation) is a security control, gated by the golden set.
7. Re-run the **golden gate on the prod OpenAI project** at cutover; add prompt-exfiltration /
   rule-override / insights-intent cases.

### 5b. Application follow-ups
8. **Admin-login lockout / throttle** on the Basic path as a stopgap until the IdP (2) lands. *(R1)*
9. **Audit tamper-evidence** — per-record hash chain (or WORM / append-only external store) and a
   **Mongo role scoped so the app cannot update/delete the `audit` collection.** *(R3)*
10. **Per-turn wall-clock timeout + concurrent-stream ceiling** on the request path, and a **global
    OpenAI spend circuit-breaker** (pairs with alerting, 5). *(R4)*
11. **Widget `frame-ancestors` allowlist** — serve `Content-Security-Policy: frame-ancestors
    <approved embedders>` for the widget document per customer. *(R5)*
12. **Reconcile the widget session-token storage** with the invariant — keep it in memory, or
    document the `sessionStorage` reconnect trade-off and fix the contradicting comment. *(R6)*
13. **At-most-once crash-window** — write a "send-attempted" marker (or the external reference)
    *before* the webhook/email call so a reclaimed job parks instead of blind-resending. *(R7)*
14. **Rate-limit feedback + control-char-normalize free text.** *(R8)*
15. **Browser-verify the CSP** at staging (open the widget + admin, confirm no console violations)
    before prod cutover. *(R9)*

---

## 6. Notes on specific concern areas

- **Prompt injection / LLM:** contained by design — read-only tools, no model-driven side effects,
  approved-only content, output-token cap. The only residual is admin-plane: attacker text reaching
  the insights summarizer can queue an **unserved draft** FAQ (never public; a reviewer-social-
  engineering surface). Flag insights-owned drafts as untrusted in the admin UI and cover
  exfiltration/override attempts in the golden set.
- **Usage / abuse / cost:** app-level per-session/per-IP throttles + spoof-resistant client IP are
  in place; the remaining exposure is volumetric/bot, which the edge WAF (5a.1/3) closes.
- **Inappropriate input & sanitization:** validated for length + email format; fields are
  length-bounded; there is **no content-moderation pass** on input or model output (acceptable for a
  read-only bot with no XSS sink — revisit only if moderation becomes a business requirement).
  Control-char normalization is a low follow-up (R8).
- **Admin portal:** authorization is strong; the open items are authentication (R1) and audit
  tamper-evidence (R3).

---

## 7. V2 (forward-looking, not a V1 gap)

When authenticated clients / tenancy arrive, every ID-parameterized admin/client route needs a
per-actor ownership/tenant check or it becomes a cross-tenant IDOR (the repository layer and
contracts §11 already anticipate `tenant_id`/`account_id`). The tool-authorization model must gain
per-call tenant/role validation before any client-scoped or private-store tool exists. Private
Vector Stores must be application-selected, never model-selected.
