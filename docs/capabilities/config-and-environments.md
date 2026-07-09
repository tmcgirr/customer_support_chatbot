# Configuration, prompts & environments

> **In one line:** A single, fail-closed configuration source plus versioned system prompts and separate staging/production environments, so the bot's behavior and secrets are explicit, reviewable, and never edited live in production.

**Status:** Live on staging (production stack authored, not yet stood up)  ·  **Introduced:** V1

## What it is
Everything the app needs to run — model choice, MongoDB connection, session secrets, abuse caps, feature flags, delivery transport, retention periods — comes from **one** typed settings object (`app/core/config.py`). The system prompt that steers the model is a **versioned** markdown file (`sys-vN.md`), pinned by a constant, so a wording change is a deliberate, diff-able edit. And there are **two isolated environments** — staging and production — each with its own MongoDB, OpenAI project, and Vector Store. Approved content, prompts, and model config are *promoted* between them behind the golden-set gate; production is never hand-edited.

## Why it exists
A public-facing bot that speaks for a consultancy fails dangerously if it boots half-configured (a default admin password, an unset Vector Store, a localhost database pointed at the internet) or if someone quietly retunes the live prompt or model. Two invariants close those gaps: **#14** (staging and production are separate; changes are promoted, never edited in prod) and **#15** (prompts and model config are versioned; changing either must pass the golden gate on the target config, and an approved fallback model is configured). Centralizing config also enforces CLAUDE.md's rule that the app reads environment values in exactly one place — nowhere else touches `os.environ`. Hosting choices trace to [ADR-013](../03_Architecture_and_Decision_Records.md) (DigitalOcean); the promotion gate to [ADR-018](../03_Architecture_and_Decision_Records.md) (golden set as a release gate).

## How it works
- **One source, fail-closed.** `Settings` (pydantic-settings) loads from env vars / `.env`; `get_settings()` is the only accessor. `ENV` **defaults to `prod`**, so a deploy that forgets to set it fails *closed* rather than booting on dev placeholders. A startup validator rejects any non-dev environment that still carries a placeholder, empty, `REPLACE_*`, or localhost value for the secrets and required inputs (session secret, admin password, OpenAI key + Vector Store, non-localhost Mongo URI and CORS origins) — a half-configured staging/prod container refuses to boot.
- **Versioned prompts.** Prompts live under `app/agent/prompts/`; `app/agent/prompt.py` pins `CURRENT_PROMPT_VERSION` (today `sys-v1`) and loads it. The active version is recorded on every conversation and assistant message, so you can tell which prompt produced any given answer. The evaluation harness can run an A/B against a different `sys-vN.md` before it becomes current.
- **Approved fallback model.** Config carries a primary `openai_model` and an optional `openai_fallback_model`. If the primary is unavailable *before any output has streamed*, the adapter retries once on the fallback (invariant #15); a mid-stream failure is not retried. Empty fallback = disabled.
- **Two environments.** Staging runs on a single DigitalOcean droplet (Docker Compose + Caddy); production authors a scaled, load-balanced, managed-Mongo variant. Each points at its own OpenAI project and Vector Store. See [doc 03 §V1 topology](../03_Architecture_and_Decision_Records.md) and the deploy guides.

## Key files
- `backend/app/core/config.py` — the `Settings` model, all defaults, and the `_validate_env_config` fail-closed startup guard.
- `backend/app/agent/prompt.py` — `CURRENT_PROMPT_VERSION` and the `load_system_prompt(version)` loader.
- `backend/app/agent/prompts/sys-v1.md` — the live system prompt (identity, tools, approved topics, prohibited claims, safety). Only version present today.
- `backend/app/agent/adapter.py` — where the primary/fallback model retry is applied (provider-isolated).
- `deploy/docker-compose.staging.yml` · `deploy/Caddyfile` · `deploy/staging.env.example` — staging stack (api + worker + Mongo behind SSE-safe Caddy).
- `deploy/docker-compose.prod.yml` · `deploy/Caddyfile.prod` · `deploy/prod.env.example` — production stack (managed Mongo, scaled API, security headers, load balancing).

## Interfaces
- **Config surface:** environment variables / `deploy/*.env` (gitignored on the host), consumed only via `get_settings()`. `*.env.example` documents the secrets and required inputs with `REPLACE_*` placeholders; most tuning knobs (message/rate caps, worker timings, insights budgets, retention periods) fall back to in-code defaults unless overridden.
- **Feature flags:** `ENABLE_DELIVERY`, `ENABLE_CITATIONS` — dark-launched OFF, enabled per environment.
- **Prompt version:** the `CURRENT_PROMPT_VERSION` constant (code-controlled), surfaced in eval reports and stored on conversations/messages.
- **Deploy verification:** `BUILD_SHA` is set at build/deploy time and surfaced on the admin system endpoint to confirm which build is live.
- **Promotion gate:** `uv run python -m eval.run` on the *target* config — the golden set must pass before a prompt/model/content change is promoted (see [evaluation](evaluation.md)).

## Status & limitations
- **Staging is live** on the DigitalOcean droplet, running against DO Managed MongoDB (pointed at by `staging.env`; the compose file otherwise falls back to an in-stack `mongo:7` for local dev), a staging OpenAI project, and a staging Vector Store. Request delivery there is the **`simulated` mock** transport (records what *would* be sent; needs no external creds).
- **Production is authored but not stood up.** `docker-compose.prod.yml`, `Caddyfile.prod`, and `prod.env.example` exist and the deploy mechanics are documented, but standing up prod is gated on owner/infra decisions (managed-Mongo backups + tested restore, prod OpenAI project/store, DNS, secrets manager) and the [V1 exit report](../V1_EXIT_REPORT.md) — not on engineering.
- **Only one prompt version exists** (`sys-v1`). Versioning is a discipline (a new file + a constant bump + a golden run), not an in-app prompt registry or UI.
- **Admin/viewer auth is still a shared HTTP Basic credential** with length/placeholder floors enforced at startup; the production identity provider that replaces it is a V1-security follow-up ([SECURITY_REVIEW_V1](../SECURITY_REVIEW_V1.md)), not shipped here.
- **Model and retention defaults live in code** with per-environment overrides; retention periods in particular are placeholders pending Legal/Privacy sign-off and must stay in lockstep with the privacy notice.
- **A misconfigured real delivery transport silently falls back to the mock** in dev (fails closed in non-dev). After enabling webhook/email in prod, verify the admin Requests "Channel" column reads the real transport, not `simulated`.

## Future & scaling
- **Real identity provider** for admin/viewer, replacing the shared Basic credential and the startup password-length stopgap (the config already models an optional read-only `viewer` role for it).
- **Secrets manager injection** in production (DO App Platform secrets / Vault / SOPS) instead of a plaintext `prod.env` on disk — the deploy guide already recommends it.
- **Config/prompt drift detection** between environments: because promotion is manual, a small check that the live prompt version and model match what the golden gate last approved would catch accidental hand-edits.
- **Finalize retention + consent versions** once Legal signs off, moving them from in-code placeholders to confirmed, notice-aligned values.
- **Horizontal scale is already designed in:** the API is stateless (MongoDB is the source of truth), so production can scale API replicas behind the load-balancing Caddy; the worker stays a single supervised instance because job claims are atomic.

## Related
- [Evaluation — the golden-set gate](evaluation.md) · [Canonical answers & the approval lifecycle](canonical-answers.md) · [Request delivery](request-delivery.md) · [Admin roles & audit](admin-roles-and-audit.md)
- Architecture: [ADR-013](../03_Architecture_and_Decision_Records.md) (DigitalOcean hosting), [ADR-018](../03_Architecture_and_Decision_Records.md) (golden set as release gate), and the V1 environment topology in [doc 03](../03_Architecture_and_Decision_Records.md)
- Deploy guides: [DEPLOY_STAGING.md](../DEPLOY_STAGING.md) · [DEPLOY_PROD.md](../DEPLOY_PROD.md)
- Invariants **#14** (separate environments, promotion) and **#15** (versioned prompts/model + fallback) in [CLAUDE.md](../../CLAUDE.md)
