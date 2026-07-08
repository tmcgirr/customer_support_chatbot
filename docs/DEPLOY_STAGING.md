# Deploy — Staging (DigitalOcean Droplet + Docker Compose + Caddy)

Stands up the **staging** environment: one Droplet running the FastAPI container +
Mongo (dev) behind **Caddy** (automatic HTTPS, SSE-safe). CLI-first. This is the
Phase V0 deliverable; the same shape scales to production at V8 (managed Mongo +
a second instance behind a DO load balancer).

Artifacts (in `deploy/`): [`docker-compose.staging.yml`](../deploy/docker-compose.staging.yml),
[`Caddyfile`](../deploy/Caddyfile), [`staging.env.example`](../deploy/staging.env.example).

## Environments & secrets

| Env | Where | Config source | Notes |
|---|---|---|---|
| `dev` | localhost | `backend/.env` (`ENV=dev`) | placeholders allowed |
| `staging` | Droplet | `deploy/staging.env` (on the droplet, gitignored) | real secrets required |
| `prod` | (V8) | injected env / secrets manager | separate OpenAI project + Mongo |

`ENV=staging|prod` makes the app **fail closed**: it refuses to boot unless
`SESSION_SECRET`, `ADMIN_PASSWORD`, `OPENAI_API_KEY`, `OPENAI_VECTOR_STORE_ID`, a
non-localhost `MONGO_URI`, and non-localhost `CORS_ORIGINS` are all real. Secrets
live only in `deploy/staging.env` on the droplet — never in the repo, never in logs.

## One-time setup

```bash
# 0. Prereqs: doctl authed (`doctl auth init`), a domain you control, an SSH key on DO.

# 1. Create the droplet (2GB is plenty for staging)
doctl compute droplet create cadre-staging \
  --image docker-20-04 --size s-1vcpu-2gb --region nyc1 \
  --ssh-keys <YOUR_SSH_KEY_FINGERPRINT> --wait

# 2. Point DNS: an A record for staging.example.com → the droplet's public IP
doctl compute droplet get cadre-staging --format PublicIPv4 --no-header

# 3. SSH in; get the code (clone or rsync the repo)
ssh root@<DROPLET_IP>
git clone <REPO_URL> cadre && cd cadre     # or: rsync -a ./ root@IP:/root/cadre
```

## Configure & deploy

```bash
# On the droplet, in the repo root:

# 4. Real secrets (gitignored). Generate strong values.
cp deploy/staging.env.example deploy/staging.env
sed -i "s/REPLACE_WITH_RANDOM/$(openssl rand -hex 32)/" deploy/staging.env   # do per-secret
$EDITOR deploy/staging.env        # set OPENAI_API_KEY, OPENAI_VECTOR_STORE_ID, CORS_ORIGINS, ADMIN_PASSWORD

# 5. Build the frontend so Caddy can serve it. Point the widget at the staging origin.
docker run --rm -v "$PWD/frontend":/w -w /w node:20 sh -c \
  "corepack enable && pnpm install --frozen-lockfile && \
   VITE_API_BASE=https://staging.example.com \
   VITE_ALLOWED_ORIGINS=https://staging.example.com pnpm build"

# 6. Bring the stack up (Caddy provisions TLS automatically for the domain)
export STAGING_DOMAIN=staging.example.com
docker compose -f deploy/docker-compose.staging.yml --env-file deploy/staging.env up -d --build

# 7. Seed canonical answers + upload knowledge to the STAGING Vector Store
docker compose -f deploy/docker-compose.staging.yml exec api \
  uv run python scripts/seed_canonical.py
# (run upload_knowledge.py locally against the staging OpenAI project; put the vs_ id in staging.env)
```

## Verify (Checkpoint V0 gate)

```bash
# Liveness (public) — minimal probe for the LB/uptime checks.
curl -s https://staging.example.com/healthz
# → {"status":"ok","version":"0.1.0"}

# Env / build (admin-gated) — confirm the RIGHT environment deployed. env/build
# are not on the public probe (no unauthenticated env/build fingerprinting).
curl -su "admin:$ADMIN_PASSWORD" https://staging.example.com/api/v1/admin/system
# → {"env":"staging","version":"0.1.0","build":"<sha>","feature_flags":{...}}
```

Then, in a browser at `https://staging.example.com/`:

1. Open the widget and send a message. **Watch the reply stream token-by-token**,
   not appear all at once. Buffered output means the proxy is batching — Caddy's
   `flush_interval -1` (in the Caddyfile) prevents this; if you swap in nginx, set
   `proxy_buffering off;`.
2. Admin at `/admin.html` logs in with the staging `ADMIN_USERNAME`/`ADMIN_PASSWORD`.

**Checkpoint V0 passes when** `/api/v1/admin/system` shows `env=staging` and the
widget streams progressively over HTTPS through Caddy.

## Update / redeploy

```bash
git pull
docker compose -f deploy/docker-compose.staging.yml --env-file deploy/staging.env up -d --build
# rebuild the frontend (step 5) if the widget changed
```

## Notes

- **CI deploy hook:** the `deploy` job is intentionally not wired to a host yet.
  Once the droplet exists, add a CI step that SSHes in and runs the redeploy
  command above, with the droplet host/key as GitHub secrets.
- **Production (V8):** swap Mongo for a managed instance with tested backups/restore,
  run ≥2 api instances behind a DO load balancer (SSE re-verified), add edge rate
  limiting + WAF, and use a separate OpenAI project + Vector Store.
