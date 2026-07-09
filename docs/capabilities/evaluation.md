# Evaluation — the golden-set gate & dev tool

> **In one line:** A fixed set of 39 "golden" conversations run through the real chatbot to prove — before any prompt/model/**provider**/content change ships — that answers, safety, and routing still behave exactly as designed.

**Status:** Gate/CI (release gate) + Dev-only tooling  ·  **Introduced:** V1 gate; V1.5 tool

## What it is
The evaluation harness lives in `backend/eval/`. It replays 39 curated test conversations (the "golden set") against the **real** orchestrator and the read-only tools the bot actually uses in production, then checks each response against a small set of assertions. It plays two roles: a **release gate** that blocks a change from shipping if any case fails, and a **standalone developer tool** for comparing different providers/models/prompts and producing shareable reports. It is deliberately not part of the chatbot or the admin app — it never runs in the request path.

## Why it exists
The bot's most important behaviors are the things it must *never* do: quote a price, claim a certification, confirm who a client is, promise an SLA, or break character under a prompt-injection attempt (see [canonical answers](canonical-answers.md) and CLAUDE.md content rules). Those behaviors depend on the prompt, the model, and the canonical/knowledge content — all of which can regress silently when edited. The golden set turns those rules into an automated, repeatable check so a regression is caught before promotion, not by a customer. It is the concrete mechanism behind the invariant that **prompts and model config are versioned and must pass the gate on the target config before promotion** ([ADR-018](../03_Architecture_and_Decision_Records.md), doc 03; spec in [doc 05 §8](../05_Conversation_and_Content_Specification.md)).

## How it works
- Each case is a list of user turns plus an `assert` block. The runner creates a real conversation, drives every turn through `ChatOrchestrator` + the live `ToolRegistry` (`search_knowledge`, `get_canonical_answer`, `get_portal_information`), and normalizes the final assistant turn into a `TurnResult` (response text, which canonical intent fired, offered actions, sources).
- Assertions are **pure functions** over that result, so they unit-test without the model. The six types: `must_use_canonical` (exact routed intent), `must_not_contain` (case-insensitive banned phrases), `must_offer_action`, `must_escalate`, `must_not_confirm_client`, and `must_not_break_character`. The last two match only *affirmative* confirmation/compliance phrases, so a correct refusal that echoes the user's wording still passes.
- A case passes only with zero failures; a crashed case counts as failed. Score is the pass rate; per-case latency is recorded and used only as a ranking tiebreak.
- Because cases run through the shipped orchestrator, **routing is measured exactly as it ships** — the gate catches "right answer, wrong route" as well as unsafe text.
- The harness only **reads** the current prompt/model (from settings). It never edits them; changes ship as reviewed code (versioned → gated → promoted), consistent with the staging/production promotion invariants.

## Key files
- `backend/eval/run.py` — the runner + CLI: loads cases, builds the real orchestrator, scores each case, wires the gate exit code, emits reports.
- `backend/eval/golden_set.yaml` — the authoritative **39** cases (pricing, security/compliance, client-confirmation, case studies, SLAs, AI Maturity Index, portal, identity/AI-disclosure, prompt-injection, company/service/industry, booking, escalation, off-topic).
- `backend/eval/assertions.py` — the six pure assertion evaluators + the safety phrase lists.
- `backend/eval/config.py` — `EvalConfig` (**provider**, model, fallback model, prompt version); `current_config()` is the gate baseline pulled from settings (whichever provider is the env default); `load_configs()` reads a compare file.
- `backend/eval/results.py` — `CaseResult`/`RunResult` scoring, per-category breakdown, `rank()`.
- `backend/eval/report.py` — self-contained HTML report (score card, per-case table, ranking + case×config diff matrix).
- `backend/eval/pdf.py` — downloadable PDF report via fpdf2 (no system deps).
- `backend/eval/configs.example.yaml` — template for the named configs an A-B run compares.
- Tester guide: [`docs/EVAL_TESTER_GUIDE.md`](../EVAL_TESTER_GUIDE.md).

## Interfaces
No HTTP endpoints, jobs, or admin screens — it is a command-line tool run by engineers/testers:
- `uv run python -m eval.run` — real-model gate; **exits non-zero on any failure**.
- `uv run python -m eval.run --fake` — plumbing adapter that spends no API budget; proves the harness drives every case and always exits 0.
- `--show` / `--filter <substr>` — print each case's response + routed intent / run a subset.
- `--report out.html` · `--pdf out.pdf` · `--json out.json` — shareable/archivable artifacts (writing one can never change the gate's exit code).
- `--model M` / `--prompt-version V` / `--provider {openai|anthropic}` — one-off override run (a bare `--provider` targets that provider's configured model).
- `--compare configs.yaml [--report ...]` — score several named configs, rank them, and render a case×config diff matrix showing exactly which cases a change fixed or broke. Each config carries a `provider`, so this is also the **cross-provider A-B**: gate a Claude config on the same golden set before switching the admin toggle to it (invariant #15).

## Status & limitations
- **Live as a gate.** CI runs `--fake` on every push to prove the harness works, and a separate manual-dispatch `golden-eval` job runs the real gate against the target environment's OpenAI project/store (it spends API budget, so it is not run on every commit). See `.github/workflows/ci.yml`.
- **`--compare` is intentionally not gated** — comparison is exploratory dev tooling and always exits 0.
- The gate's strength is bounded by coverage: it is 39 curated cases, not exhaustive. New risky behaviors need a new golden case to be protected.
- Fuzzy safety assertions (`must_not_confirm_client`, `must_not_break_character`) use maintained phrase lists; a novel unsafe phrasing not on the list could slip a case unless pinned via `must_not_contain`.
- Reports/PDF/JSON are developer surfaces only — no product or admin exposure, by design.

## Future & scaling
- **Grow coverage as canonical topics expand** — every new mandatory-canonical intent or sensitive topic should arrive with its golden case; the diff matrix already makes the impact of a change legible.
- **Model-graded checks** for open-ended answers (company/service/industry cases today assert safety, not a specific route) could add nuance the phrase lists can't, if the added cost/nondeterminism is acceptable.
- **Promotion automation**: wire the manual `golden-eval` job into the staging→production promotion flow so a red gate mechanically blocks promotion (invariants 14–15), rather than relying on a human to dispatch it.
- **Regression corpus from real traffic**: sampled, anonymized production conversations (masked per the admin PII rules) could seed new golden cases so the set tracks real failure modes.

## Related
- [Canonical answers](canonical-answers.md) — the routing/safety behavior most of these cases assert.
- [ADR-018 and the versioning/promotion ADRs](../03_Architecture_and_Decision_Records.md) — why the gate exists and how it fits promotion.
- [Doc 05 §8](../05_Conversation_and_Content_Specification.md) — the golden-set specification and content-owner review.
- [Doc 04 — API & data contracts](../04_API_and_Data_Contracts.md) — the request/turn contracts the orchestrator honors.
- [`docs/EVAL_TESTER_GUIDE.md`](../EVAL_TESTER_GUIDE.md) — hands-on guide for running the tool and reading reports.
