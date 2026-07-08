# QUICKSTART — Cadre AI Support Chatbot with Claude Code

This folder is a **starter package**, not the built project. It contains the project
memory (`CLAUDE.md`), the execution plan (`plan.md`), two subagents
(`.claude/agents/`), and the design docs (`docs/`). Claude Code builds everything else,
phase by phase. Docs reference: https://docs.claude.com/en/docs/claude-code/overview

## 1. Prerequisites (one-time, your machine)

- **Node.js 18+** (required by Claude Code)
- **Claude Code:** `npm install -g @anthropic-ai/claude-code`, then run `claude` once
  to authenticate. Verify with `claude --version`.
- **Python 3.12+** and **uv** (https://docs.astral.sh/uv/)
- **pnpm** (`npm install -g pnpm`)
- **Docker Desktop** (local MongoDB via compose)
- **git**, and an **OpenAI API key** (needed from Phase 2 onward)

## 2. Set up the project folder

```bash
mkdir cadre-chatbot && cd cadre-chatbot
# unzip/copy this starter package's contents here, so you have:
#   CLAUDE.md  plan.md  QUICKSTART.md  docs/  .claude/agents/
git init && git add -A && git commit -m "chore: planning docs and Claude Code setup"
cp .env.example .env          # then put your real OPENAI_API_KEY in .env (gitignored)
```

## 3. First session — kick off Phase 0

```bash
claude
```

Optional: run `/init` first. It will detect the existing CLAUDE.md; keep ours as the
base and let it append only genuinely new observations — delete anything redundant
(every line competes for attention). Then paste:

> Read CLAUDE.md and plan.md, and skim docs/03 and docs/04 for the architecture and
> contracts. Then execute **Phase 0 only**. Stop at CHECKPOINT 0, run its verification,
> and summarize what you built and what's red before doing anything else.

The checkpoint ritual, every phase: Claude runs the verification → you eyeball the
result (Phase 0: watch SSE deltas render **one by one** in the browser, not in a single
paint) → commit happens → **start a fresh session or `/clear`** before the next phase.
One phase per context window keeps quality high.

## 4. Subsequent phases

New session, then: *"Read CLAUDE.md and plan.md. Phases 0–N are done (see git log).
Execute Phase N+1. Stop at the checkpoint."*

- **Phase 3 and 5 (⚡ parallel):** tell Claude explicitly — *"Run subtasks 3A, 3B, and
  3C as parallel subagents (use widget-builder for UI work in Phase 5), then integrate
  the results yourself and run the checkpoint."*
- **Every checkpoint from Phase 4 on:** *"Use the eval-gatekeeper subagent to run the
  full gate and report."* Never accept a checkpoint where the golden set was skipped.
- Check `/agents` in-session to confirm both subagents loaded; `/memory` to review what
  Claude has learned about the repo.

## 5. When Claude generates broken code

1. Paste the **exact command** you ran and the **complete** error/traceback — never a
   paraphrase, never a fragment.
2. Ask: *"Reproduce this as a failing test first, then fix it, and keep the test."*
   This forces a fix of the cause, not the visible symptom.
3. Golden-set failures: have the eval-gatekeeper report case ID + failed assertion +
   output excerpt; rerun once to separate real regressions from LLM flake.
4. If a fix attempt loops twice without progress: `git checkout` back to the last
   checkpoint commit (this is why every phase commits), `/clear`, and re-attempt with
   the full error context included in the *first* message.

## 6. Human-only tasks (Claude Code cannot do these)

- Put the real `OPENAI_API_KEY` in `.env` (Phase 2+). Never paste keys into the chat.
- Deploy the Phase 0 skeleton to DigitalOcean and verify SSE streams **unbuffered**
  through the real routing path before Phase 5 (see plan.md deploy note).
- Assign the content owners in docs/06 §6 — content approval is the critical path.

## Layout after Phase 0 (Claude creates this)

```
cadre-chatbot/
├── CLAUDE.md  plan.md  docs/  .claude/agents/     # this package
├── backend/app/{api,core,domain,agent,jobs}/  backend/eval/  backend/tests/
├── frontend/src/
├── scripts/  docker-compose.yml  .github/workflows/ci.yml  .env(.example)
```
