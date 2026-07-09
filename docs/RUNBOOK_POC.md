# RUNBOOK — Cadre AI Support Chatbot (POC)

Operational guide for running, seeding, deploying, and maintaining the POC.
Architecture recap: FastAPI backend + React iframe widget + MongoDB (the single
source of truth) + OpenAI Responses API (stateless, `store=False`). See
`docs/03_Architecture_and_Decision_Records.md` for the why.

---

## 1. Configuration (environment)

All config is read in **one place** — `backend/app/core/config.py` — from
`backend/.env` (never committed) or real environment variables. Copy
`.env.example` to `backend/.env` and fill it in. Full list:

| Variable | Default | Notes |
|---|---|---|
| `ENV` | `dev` | Any non-`dev` value **fails startup** if a default secret is still set. |
| `OPENAI_API_KEY` | — | Required. Live key; never commit or log. |
| `OPENAI_MODEL` | `gpt-5.4-mini` | Chat model (Responses API). |
| `OPENAI_VECTOR_STORE_ID` | — | Set after `upload_knowledge.py`. |
| `MONGO_URI` | `mongodb://localhost:27017/cadre_chatbot` | May embed credentials (secret). |
| `SESSION_KEY_ID` / `SESSION_SECRET` | `k1` / `dev-only-change-me` | HMAC session tokens. **Change in prod.** |
| `SESSION_EXTRA_SECRETS` | — | Retired keys still trusted for verification: `kid:secret,...`. |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / `dev-only-change-me` | Admin Basic auth. **Change in prod.** |
| `PORTAL_URL` | `https://portal.cadreai.com` | Placeholder — real portal URL owned by Client Success. |
| `MESSAGE_CAP` | `40` | Max user turns per conversation. |
| `MESSAGE_MAX_CHARS` | `2000` | Max chars per user message. |
| `IP_CREATE_CAP` | `10` | Conversations per IP per window. |
| `IP_CREATE_WINDOW_SECONDS` | `3600` | Rolling window for the IP cap. |
| `LOCK_STALE_SECONDS` | `120` | A run lock older than this is treated as leaked. |
| `CORS_ORIGINS` | `http://localhost:5273` | Comma-separated allowed widget origins. |

**Secret guard:** with `ENV` set to anything but `dev`, the app refuses to start
while `SESSION_SECRET` or `ADMIN_PASSWORD` is still the in-repo default (or empty).
This is the intended prod safety net — set real secrets before deploying.

---

## 2. Run locally

```bash
# MongoDB only (the app runs on the host)
docker compose up -d mongo

# Backend  (:8000)   — from backend/
uv sync
uv run uvicorn app.main:app --reload --port 8000

# Widget + admin UI  (:5273)  — from frontend/
pnpm install && pnpm dev
#   widget: http://localhost:5273/         admin: http://localhost:5273/admin.html
```

Full dockerized stack (deploy shape, api on :8080):

```bash
docker compose --profile full up --build
```

---

## 3. Seed & knowledge scripts (run from `backend/`)

```bash
# Canonical approved answers (pricing, security, AI Maturity, portal, ...).
# Idempotent — keyed by intent, safe to re-run. MUST re-run after editing seeds.
uv run python scripts/seed_canonical.py

# Push docs/knowledge/ to the OpenAI Vector Store, then copy the printed
# vs_... id into OPENAI_VECTOR_STORE_ID in backend/.env.
uv run python scripts/upload_knowledge.py

# Release leaked run-locks (crashed-mid-turn). Safe on a cron; a live turn has a
# young lock and is untouched. The send path already recovers locks lazily.
uv run python scripts/sweep_locks.py                 # uses LOCK_STALE_SECONDS
uv run python scripts/sweep_locks.py --older-than 300
```

---

## 4. Golden evaluation gate

The golden set MUST pass before any prompt/model/canonical change is committed.

```bash
# Real gate — spends OpenAI credits; needs OPENAI_API_KEY + seeded canonical.
uv run python -m eval.run

# Plumbing check only (no API spend), for local/CI smoke:
uv run python -m eval.run --fake
```

CI runs the real gate as a manual `workflow_dispatch` job (`golden-eval`) so a
regression in content rules is caught before release.

---

## 5. Manual data deletion (privacy request)

Because MongoDB is the **single source of truth** and every model call uses
`store=False` (no provider-side retention, no OpenAI Conversation objects),
deleting a person's data is a **single-collection** operation — there is nothing
to delete on OpenAI's side.

```javascript
// mongosh against the app database
use cadre_chatbot

// 1. Find the conversation(s). If you only have a masked email from the admin
//    view, locate by request reference or conversation_id instead — message
//    content is stored verbatim, so a substring match on messages.content works.
db.conversations.find({ "messages.content": /jane@acme\.com/ }, { _id: 1 })

// 2. Delete the conversation document (removes its full transcript, including
//    any unsupported_questions recorded from it).
db.conversations.deleteOne({ _id: "cnv_..." })

// 3. Delete any requests filed from that conversation (contact email/company).
db.requests.deleteMany({ conversation_id: "cnv_..." })

// 4. Delete any feedback rows for that conversation.
db.feedback.deleteMany({ conversation_id: "cnv_..." })
```

`rate_limits` holds only HMAC'd IP counters that TTL-expire on their own — no PII,
nothing to delete. Session tokens are stateless (no session collection).

---

## 6. Deploy (POC shape)

1. Provision MongoDB (Atlas or a managed instance); put its URI in `MONGO_URI`.
2. Set **all** secrets as real environment variables and set `ENV=staging`/`prod`
   (startup will refuse default secrets — that's the point).
3. Set `CORS_ORIGINS` to the real host page origin(s); set
   `VITE_ALLOWED_ORIGINS` for the widget build to the same.
4. Build & run the container: `docker compose --profile full up --build`
   (api listens on `:8000` in-container, mapped to `:8080` in compose). Front it
   with a TLS-terminating proxy that sets a trustworthy `X-Forwarded-For`.
5. Seed canonical answers and upload knowledge (§3); set `OPENAI_VECTOR_STORE_ID`.
6. Build the frontend (`pnpm build`) and serve `dist/` (widget `index.html`,
   admin `admin.html`) from the host page / a static host.
7. Smoke-test the six PRD scenarios (see `docs/POC_EXIT_REPORT.md`).
8. Schedule `scripts/sweep_locks.py` (e.g. every 5 min) as a safety net.

---

## 7. Common issues

| Symptom | Likely cause / fix |
|---|---|
| App won't start, "insecure default secret(s)" | `ENV` is non-dev but `SESSION_SECRET`/`ADMIN_PASSWORD` still default — set real values. |
| `429 RATE_LIMIT` on create | Per-IP cap hit; raise `IP_CREATE_CAP` or wait out `IP_CREATE_WINDOW_SECONDS`. Many users behind one NAT share an IP. |
| Conversation stuck `CONVERSATION_BUSY` | Leaked lock; the next send auto-recovers after `LOCK_STALE_SECONDS`, or run `scripts/sweep_locks.py`. |
| Model answers off-script / invents facts | Re-run `seed_canonical.py`; verify `OPENAI_VECTOR_STORE_ID`; run the golden gate. |
| Widget can't connect | Check `CORS_ORIGINS` / `VITE_ALLOWED_ORIGINS` and that the backend is on :8000. |
