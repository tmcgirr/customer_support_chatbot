# Cadre AI Customer Support Chatbot
## V2 — Authenticated Client Support: Capability & Direction Plan

**Status:** Proposed forward direction (V2). **Not in build.** This document explains where the
delivered POC/V1 can go if the business approves a production-grade authenticated build, and how
we would build it to best practice.
**Depends on:** delivered POC/V1; ADR-020 (agent runtime choice) and ADR-021 (authenticated trust
tier) in doc 03.
**Extends:** doc 02 §6 (V2+ Direction) and doc 06 §14 (Epic E12) with an actual design.

---

# 1. How to read this

The POC/V1 delivered a **public, anonymous** support assistant that answers from approved content
and never acts on the visitor's behalf. It works and is production-gate-ready (see
`V1_EXIT_REPORT.md`). This plan describes the **next trust tier**: a **logged-in customer** who can
ask about *their own* account, portal, and tickets, and — carefully — have the assistant *do* things
for them.

This is a **direction and options** document, not a commitment or a sprint plan. Where a real choice
is required (identity source, which integrations, appetite for automated actions), it is called out
as **[Decision required]** and collected in §14. Nothing here changes the shipped product; it defines
what a responsible V2 build would contain and the order we would build it in.

The organizing idea is unchanged from V1 and is the reason the system is safe to extend:

> **The model looks things up; the application decides everything with a side effect.** V2 does not
> abandon that boundary — it opens a *second, narrower* one for authenticated users, with the model
> allowed to act only through guarded, per-request-authorized tools.

---

# 2. What V2 adds (and deliberately does not)

**Adds:** authenticated identity, tenant isolation, private per-tenant knowledge, tenant-scoped read
tools (account, portal, ticket status), pre-filled and — selectively — automated actions, and
human takeover to a live person.

**Does not change:** the public anonymous tier (it stays exactly as shipped), MongoDB as the single
source of truth, provider isolation, the golden-set release gate, or the "no PII in logs / masked by
default / audited reveal" posture. V2 is **additive** and gated behind login; an anonymous visitor
sees no change.

---

# 3. The principle that scales: two trust tiers, two rules

| | **Tier 1 — Public (shipped)** | **Tier 2 — Authenticated (V2)** |
|---|---|---|
| Who | Anonymous website visitor | Logged-in Cadre client / employee |
| Identity | Stateless conversation-scoped HMAC token | Real identity + tenant + role (from the portal) |
| Model tools | 3 read-only, public only | Public + tenant-scoped reads + guarded action tools |
| Can the model write? | **No** — never in the write path | **Only** via guarded tools with per-call authorization; high-stakes actions still confirm |
| Knowledge | One public Vector Store | Public store + a **private, per-tenant** store (application-selected) |
| Rule | *Model is strictly read-only* | *Model may act, but the application authorizes every action from the session, never from the model* |

Keeping these as distinct tiers — rather than "flags on one bot" — is what prevents the powerful
authenticated capabilities from ever leaking to the anonymous internet surface. This is formalized in
**ADR-021**.

---

# 4. Identity & tenancy

**Recommendation: reuse the existing Cadre client portal as the identity source (SSO), not a new
login inside the widget.** The widget is embedded on pages where the customer is already
authenticated to the portal; the host page hands the iframe a short-lived, signed token
(origin-checked `postMessage`, as today), which the API exchanges for an authenticated session
carrying `{ subject, tenant_id, role, exp }`. Benefits: no second credential store, no password entry
in an iframe, and the portal remains the system of record for who a customer is.

**Tenant resolution** happens once, server-side, at session establishment — never from anything the
model or the browser asserts later. Every downstream read and write is scoped by the `tenant_id` on
the session.

**Roles** start minimal (e.g. `client_user`, and later `client_admin` for org-level views), mirroring
the deliberate two-role restraint of the admin console. More roles only with demonstrated need.

> **[Decision required]** Identity source: portal SSO (recommended) vs. a standalone auth. This single
> choice most shapes the build — resolve it first.

---

# 5. The capability map (by risk)

Grounded in what the Cadre portal actually offers (tracking a client's AI tools, agents, and results)
and the V2 goals already in the PRD (ticket status, human takeover):

| Capability | Example ask | Pattern | Model in write path? |
|---|---|---|---|
| **Private reads** | "Show my active AI tools & agents and their latest results." "What plan am I on?" | Tenant-scoped read tool + private store; authorization inside the tool | No |
| **Ticket status** | "What's the status of my support ticket?" | Tenant-scoped read against ticketing | No |
| **Prepared actions** *(default for writes)* | "Open a support ticket." — pre-filled from the account, user confirms | Model proposes → user confirms → typed endpoint commits → worker delivers (today's pattern, richer) | No |
| **Human takeover** | "Get me a person." | Route to a live agent (WebSockets) with full context | No (routing) |
| **Direct actions** *(opt-in, per action)* | "Resend my last invoice to me." "Mark these notifications read." | Guarded write tool commits directly; per-action risk review | **Yes** — low-stakes, reversible, idempotent only |

Most of the value — personalized answers, ticket status, pre-filled requests — sits in the first four
rows, which keep the model **out of the write commit** even for logged-in users. The last row is the
only place the trust boundary actually moves, and it moves **one action at a time**, each individually
approved.

---

# 6. Private knowledge (per-tenant stores)

Following **ADR-012**, private knowledge lives in **separate Vector Stores per security domain**,
**selected by the application from the session's `tenant_id` — never by the model.** A tenant's
retrieval tool can only ever query that tenant's store plus the shared public store. This is the same
"forced `audience=public`" discipline the V1 retrieval boundary already uses, extended to
"forced `tenant_id = <session tenant>`."

Best practice we would hold: no cross-tenant retrieval is *possible*, not merely *unlikely* — the
store id is derived server-side and the model has no parameter that can widen it.

---

# 7. Tools, integrations & MCP

- **Capability-scoped tool registry.** The set of tools a turn is offered is resolved **per request
  from the authenticated principal**. Anonymous → the 3 public tools (unchanged). Authenticated → those
  plus tenant-scoped reads and any guarded actions the tenant/role permits. This is a small extension
  of the existing `ToolRegistry` seam.
- **Authorization from the session, never the model.** A tool such as `get_account(…)` derives the
  account from the session's `tenant_id` and **ignores** any identifier the model supplies. The model
  is untrusted input; it can be wrong or be injected. Each authenticated tool performs its own per-call
  tenant/role check.
- **Integrations behind adapters.** CRM, billing, portal, and ticketing systems sit behind normalized
  adapters exactly like the model and delivery layers do today — their SDK types, ids, and errors never
  leak past their module. Downstream code and the public API see only local ids and normalized results.
- **MCP as a transport, decided on its own merits.** The Model Context Protocol is an attractive,
  standard way to *expose* these integrations as tools, and it is **orthogonal** to the agent-runtime
  choice (it works with the current custom loop or any framework). If adopted, the same rules apply:
  authorization from the session, and each MCP server treated as a **new trust/injection surface**
  (its tool descriptions and outputs are model-influencing content and must be handled as untrusted).

---

# 8. The agent runtime at V2

The current hand-written read-only loop is the right choice for the shipped scope (see **ADR-020**).
V2 is the first scope where a framework's features — a managed multi-agent loop, handoffs, durable
workflows — actually have work to do. **ADR-020** records how we would decide:

- Extend the custom loop for tiers of work that stay read-only or use the prepared-action pattern
  (most of §5).
- Re-evaluate the **OpenAI Agents SDK** (if OpenAI-committed and handoff-heavy) vs. **LangGraph** (if we
  need durable, branching, human-in-the-loop workflows and model-agnosticism) at the point the model
  genuinely enters the write path across multi-agent workflows.
- Adopt whichever wins **behind the existing `ModelAdapter`/registry boundary**, with its session or
  checkpointer backed by MongoDB (so the single-source-of-truth invariant holds), and provider
  isolation preserved. Never a big-bang rewrite of the working public flow.

---

# 9. Human takeover

A live-agent handoff (WebSockets, per doc 02 §6) lets the assistant escalate a logged-in customer to a
person with the full conversation and account context attached. This is a routing capability, not a
model write. It introduces an operational owner question (**[Decision required]**: who staffs it, and
hours) and a presence/queueing surface, but no new model-trust risk.

---

# 10. Data, history, retention & privacy at the tenant tier

- **MongoDB stays the single source of truth.** Authenticated conversations are stored in Mongo,
  **tenant-scoped**. Per **ADR-015**, once threads can exceed the public cap, tenant conversations move
  to a **separate messages collection** behind the repository interface — a contained change, not a
  redesign. There is still exactly **one** history store; nothing is written to the model provider or an
  SDK session as a second copy.
- **Per-tenant retention and deletion.** Retention classes and verified deletion (already job-driven in
  V1) extend to tenant scope; a client's data is deletable as a single-store operation plus documented
  provider terms. Regional retention is a **[Decision required]** if enterprise/regional customers are
  in scope.
- **Object-scope authorization everywhere.** Every authenticated read and write is checked against the
  session's tenant — closing the cross-tenant (IDOR) surface the V1 security review flagged as the thing
  that appears "the moment tenancy arrives." The seams for `tenant_id`/`account_id` are already
  anticipated in the code.

---

# 11. Best-practice guardrails (how we would build it responsibly)

The point of V2 is *more capability without more risk*. The non-negotiables:

1. **Least privilege.** A turn gets the smallest toolset its principal allows; a tool touches only the
   session's tenant.
2. **Authorization from the session, not the model.** The single most important rule — the model never
   supplies its own authorization scope.
3. **Confirm high-stakes, automate only the reversible.** Anything that contacts a human, creates a
   record, or moves money is confirmed by the user. Direct model actions are limited to low-stakes,
   reversible, idempotent operations, each individually risk-reviewed.
4. **Everything auditable.** Every authenticated action and every access to private data is an
   append-only audit record (extending the V1 audit trail), with the actor being the real customer
   identity.
5. **Isolation by construction.** Private stores and tenant reads are scoped server-side so
   cross-tenant access is impossible, not merely discouraged.
6. **Untrusted content discipline.** Private documents and MCP-server outputs are model-influencing
   content and are treated with the same injection defenses as public retrieval.
7. **The release gate still gates.** The golden set expands with authenticated cases (correct tenant
   scoping, correct escalation, no cross-tenant leakage) and remains a hard gate for any prompt, model,
   tool, or provider change.

---

# 12. Responsible rollout — the phased sequence

Ordered so each phase ships value and the trust boundary moves **only once, deliberately, at the end**.

| Phase | What ships | What stays fixed |
|---|---|---|
| **0 — Identity & tenancy** | Production identity provider (also a V1 launch-gate item) + tenant/identity data model + portal SSO hand-off | Public tier untouched |
| **1 — Capability-scoped registry** | Tools resolved per authenticated principal; anonymous behavior byte-identical | Model still read-only |
| **2 — Private reads + private store** | Tenant-scoped read tools + per-tenant Vector Store; personalized answers | Model still out of the write path |
| **3 — Prepared actions** | Pre-filled requests/tickets from real account data, confirm-to-submit; human takeover | Side effects still user-confirmed |
| **4 — Direct actions + runtime decision** | Per-action guarded write tools (the trust-boundary amendment) + the Agents SDK / LangGraph evaluation + any MCP integrations | History stays in Mongo, tenant-scoped; authorization from session |

Phases 0–2 deliver the bulk of the "authenticated" experience at low risk. Only Phase 4 crosses the
write boundary, and only per-action.

---

# 13. Measurement & attribution — future enhancement options

These are **direction and options** for proving and improving the chatbot's business value. Two are
worth recording alongside the V2 picture because they close measurement gaps V1's funnel leaves open.
Both are **nearer-term than the authenticated tier** — neither requires customer login — and both are
**cheap to run**: the runtime model cost is near-zero, so the real investment is engineering plus one
integration each, and their *value* is gated on closed-deal volume, not on tokens.

Context: V1's funnel ends at **`requested`** (an in-widget form submission — a lead, not a deal). Two
outcomes stay invisible: whether a lead **signed**, and whether a visitor converted on the **website**
instead of in the widget.

## 13.1 Close-loop attribution — conversation → signed contract

**What it is.** Tie each conversation to its downstream deal outcome, so the business can see which
conversations become signed contracts and mine the transcripts for the conversation *styles and paths*
that close best (e.g. does an advisory "let's plan this" conversation close better than an early "book
a call" pitch? does pushing the pitch early turn people away?).

**How it fits.** The join key already exists: a converted conversation creates a `requests` record, and
delivery stores the CRM **external reference** (opportunity/contact id). A **worker job reads the deal
stage back** by that reference and stamps a normalized `deal_outcome` (`booked | qualified | won | lost`,
close date, value band) onto the conversation. This is a worker-owned CRM **read behind an adapter**
(invariant #4) — no model involvement, provider ids stay internal, and deal value/identity are PII
(masked by default, audited reveal, retention-classed). It needs only the CRM connected, which
strategy-call delivery already requires, so it does **not** depend on the authenticated (V2) build.

**Feature extraction.** Per conversation: **path features** (turn count, tools used, topic/intent, when
the strategy-call action was offered, whether pricing/security came up) are **free** — aggregation over
metadata already stored. **Style features** (advisory ↔ transactional, a value-delivered / sentiment
trajectory signal, expressed intent) are the only new model cost, and the efficient design is to **fold
them into the per-conversation summary/label `classify` the worker already runs** — a richer output
schema, not a new call — so the marginal cost is a few output tokens.

**Analysis, honestly.** Segment close-rate by feature to test those hypotheses. But a consultancy signs
**dozens** of deals a year, not thousands, so automated "style → close" correlation is statistically
weak at first. **Lead with the qualitative win the linkage unlocks** — surface the transcripts that
actually closed for human review — and add quantitative segmentation only as closed-deal volume supports
significance.

> **[Decision required]** Connect the CRM's read side (deal-stage read-back) — a small addition to the
> existing delivery/CRM integration. Owner: Engineering / Sales.

## 13.2 Cross-channel attribution — chat ↔ the site form

**What it is.** Credit conversions that happen **off the widget**. A visitor chats, then signs up through
the **website** form rather than the in-chat action; today that reads as a chat failure even though the
chat may have done the convincing.

**How it fits.** A first-party, **consented, anonymous visitor id** set on the host page is shared with
both the widget (origin-checked `postMessage`, as today) and the site's signup form; a worker join links
"this site signup had a prior chat session within N days." First-party only, no third-party trackers —
consistent with the privacy posture. **No model cost**; the cost is site instrumentation plus a join job.

**What it answers.** *Assisted conversions* (chat → later site signup) recover value that in-widget-only
attribution undercounts — often how the whole channel is justified. *Channel preference* (of chatters who
convert, what share do it in the widget vs. on the site) is the direct "do people trust the site form
more — should we hand off to it?" signal. And it separates a *true drop* (converted nowhere) from a
*deflection* (converted elsewhere). This one pays off **immediately, even at low deal volume**.

> **[Decision required]** Instrument a shared first-party visitor id across the host page, widget, and
> site form (consented). Owner: Engineering / Marketing.

## 13.3 Cost and sequencing

The analytics themselves are cheap; the decision is engineering time, not tokens.

| Component | Model cost | The real cost |
|---|---|---|
| Path features (turns, tools, topics) | $0 — already stored | Engineering only |
| Style features — **folded** into the existing `classify` | ~pennies / 1k conversations | Engineering (schema) |
| CRM deal-outcome sync | $0 | CRM read adapter + poll job |
| Cross-channel join | $0 | Site instrumentation + join job |

**Recommended order:** (1) cross-channel attribution + the conversation↔deal linkage first — both
model-free, both correct the ROI story, both inform a real product decision (in-chat form vs. site
hand-off); (2) fold style features into the existing per-conversation classifier now, so data accrues
before volume arrives; (3) defer automated close-pattern mining until closed-deal volume supports
significance — until then, read the winning transcripts qualitatively.

---

# 14. Decisions the business owns

| Decision | Why it matters | Likely owner |
|---|---|---|
| **Identity source** — portal SSO (recommended) vs. standalone login | Shapes the entire auth design; resolve first | Engineering / Product |
| **Which integrations** (portal, CRM, billing, ticketing) and in what order | Defines the tenant-scoped tool set | Product / Client Success |
| **Appetite for direct (automated) actions**, and which ones | Determines whether/when the model enters the write path | Leadership / Security |
| **Human-support ownership** (staffing, hours, tooling) | Required before human takeover ships | Client Success |
| **Regional / compliance requirements** (residency, retention) | May change store, retention, and hosting design | Legal / Security |
| **Agent-runtime path** at Phase 4 (extend custom / Agents SDK / LangGraph) | Recorded framework decision; see ADR-020 | Engineering |
| **CRM deal-stage read-back** (close-loop attribution, §13.1) | Enables conversation→signed-contract measurement | Engineering / Sales |
| **Shared first-party visitor id** (cross-channel attribution, §13.2) | Credits off-widget conversions; informs in-chat form vs. site hand-off | Engineering / Marketing |

---

# 15. Entry criteria — the V2 design gate

Before any build starts, doc 02 §8's V2 design gate must be satisfied: tenant/authorization model
approved; client retention defined; private-knowledge isolation selected; tool authorization formally
designed (ADR-021); human-support ownership defined; regional/contractual requirements known. This plan
is the input to that gate, not a substitute for it.

---

# 16. What stays fixed, no matter how far V2 goes

- The public tier stays read-only and unchanged.
- MongoDB is the single source of truth; there is never a second history store.
- External systems (providers, CRM, ticketing, MCP) stay behind adapters; local ids leave, provider ids
  stay in.
- Authorization is resolved from the session; the model never authorizes itself.
- The golden set gates every prompt/model/tool/provider change.

---

# 17. References

- Direction: doc 02 §6 (V2+), §8 (V2 design gate); doc 01 §3.3 (long-term goals); doc 06 §14 (E12).
- Measurement & attribution (§13): builds on the existing conversion funnel, the `llm_usage` cost
  rollup, and delivery's stored external reference; see `docs/capabilities/analytics-and-insights.md`.
- Decisions: **ADR-012** (public/private stores), **ADR-015** (tenant messages collection), **ADR-019**
  (async delivery), **ADR-020** (agent runtime), **ADR-021** (authenticated trust tier) — doc 03.
- Posture carried over: `SECURITY_REVIEW_V1.md` (the tenancy/IDOR forward note), `CLAUDE.md` invariants
  (esp. #2 read-only model, amended for the authenticated tier by ADR-021; #4 provider isolation; #14/#15
  environments & gating).
