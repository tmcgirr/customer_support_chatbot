# Deploy — Production (V8)

Stands up the **production** environment, separate from staging (invariant 14). Same
container shape as staging, but: a managed MongoDB (no in-stack Mongo), the API scaled
behind a load-balancing Caddy, security headers, and a separate OpenAI project + Vector
Store. CLI-first.

Artifacts (`deploy/`): [`docker-compose.prod.yml`](../deploy/docker-compose.prod.yml),
[`Caddyfile.prod`](../deploy/Caddyfile.prod), [`prod.env.example`](../deploy/prod.env.example).

> Gate: do NOT open public traffic until `docs/V1_EXIT_REPORT.md` items are closed. This
> guide is the cutover mechanics; the exit report is the go/no-go.

## Prerequisites (owners in doc 06 §6)

- **Managed MongoDB** provisioned with automated backups (Atlas or self-hosted — Engineering
  decision) and a **tested restore** (`scripts/restore_mongo.sh`, see RUNBOOK). A real,
  non-localhost `MONGO_URI` with credentials for a dedicated `cadre_chatbot` prod database.
- **Production OpenAI project** + a **separate Vector Store** (never the staging store).
- **DNS**: an A record for the prod domain → the host (or the DO load balancer).
- **Secrets** available to inject (prefer a secrets manager over a file on disk).

## Configure & deploy

```bash
# On the prod host, in the repo root:

# 1. Real secrets (gitignored). Prefer injecting from a secrets manager; a file is the
#    fallback. ENV=prod REFUSES to boot on any placeholder/localhost value.
cp deploy/prod.env.example deploy/prod.env
$EDITOR deploy/prod.env    # MONGO_URI, OPENAI_* (prod project+store), SESSION_SECRET,
                           # ADMIN_PASSWORD, CORS_ORIGINS (real https), BUILD_SHA, PROD_DOMAIN

# 2. Build the widget/admin for the prod origin.
docker run --rm -v "$PWD/frontend":/w -w /w node:20 sh -c \
  "npm i -g pnpm@9 && pnpm install --frozen-lockfile && \
   VITE_API_BASE=https://$PROD_DOMAIN \
   VITE_ALLOWED_ORIGINS=https://www.cadre.ai,https://cadre.ai \
   VITE_PRIVACY_URL=https://cadre.ai/privacy \
   VITE_PORTAL_URL=https://portal.cadre.ai pnpm build"

# 3. Bring up the stack with 2 API replicas behind the load-balancing Caddy.
export PROD_DOMAIN=chat.cadre.ai
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/prod.env \
  up -d --build --scale api=2

# 4. Seed approved canonical answers + upload knowledge to the PROD Vector Store.
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/prod.env exec api \
  uv run python scripts/seed_canonical.py            # then approve via admin (V5)
# (run scripts/upload_knowledge.py against the PROD OpenAI project; set OPENAI_VECTOR_STORE_ID)
```

## Verify (production cutover checklist)

```bash
B="https://$PROD_DOMAIN"
curl -s $B/healthz                                   # {"status":"ok",...}
curl -su "admin:$ADMIN_PASSWORD" $B/api/v1/admin/system      # env=prod, build=<sha>
curl -su "admin:$ADMIN_PASSWORD" $B/api/v1/admin/monitoring  # queue_depth/dead_letter/... = 0
```

Then:
1. **Golden gate on the prod config** — run `uv run python -m eval.run` against the prod
   OpenAI project/store. MUST be green before traffic.
2. **SSE through the LB** — open the widget at `$B/`, send a message, watch the reply stream
   token-by-token (not one paint). Verified via the LB in V8; re-confirm on the real host.
3. **Admin roles** — viewer login is denied reveal/redeliver/approve (403).
4. **Retention/deletion** — a verified deletion purges a subject; retention sweep runs.
5. **Failure paths** — force `MODEL_UNAVAILABLE` (fallback model), a delivery failure
   (dead-letter → admin redeliver).
6. Confirm `docs/V1_EXIT_REPORT.md` items 1–2, 5–8 on the real environment.

## Scale / redeploy / rollback

```bash
# Scale API replicas (stateless — Mongo is the source of truth):
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/prod.env up -d --scale api=3

# Redeploy after a release:
git pull && docker compose -f deploy/docker-compose.prod.yml --env-file deploy/prod.env \
  up -d --build --scale api=2      # rebuild the widget (step 2) if the frontend changed

# Rollback: check out the previous tag/sha and re-run the redeploy command.
```

The worker runs as ONE supervised instance (atomic job claim makes >1 safe; one is
sufficient and avoids redundant periodic scheduling). See `docs/RUNBOOK_PROD.md` for
monitoring thresholds, backups, secrets rotation, and incident response.
