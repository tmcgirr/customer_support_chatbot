# Backend — Cadre AI chatbot

FastAPI modular monolith + a dedicated background worker + the standalone evaluation harness.
Python 3.12, async throughout (`motor`), Pydantic v2, packaged with `uv`.

See the repo [README](../README.md) and the [Capabilities Catalog](../docs/capabilities/) for the
product picture; this file is the developer orientation.

## Layout

```
app/
  api/        HTTP layer. public/ (widget-facing), admin/ (console), deps, sse, health
  agent/      model orchestration — orchestrator, adapter (OpenAI Responses), tools, prompts/
  core/       config, ids, security (HMAC), masking, logging, errors, db
  domain/     one package per capability, each: models → repository → service
              canonical · knowledge · requests · delivery · jobs · audit · privacy ·
              analytics · insights · conversations · monitoring · aggregates · ratelimit · feedback
  main.py     API app factory
  worker.py   background worker entrypoint
eval/         standalone golden-set evaluation tool (dev-only; never imported by the app runtime)
scripts/      seed_canonical · upload_knowledge · sweep_locks · approve_canonical · chat_repl
tests/        mirror app/ — mock the model at its adapter boundary (FakeAdapter), never call a real API
```

**Architecture rules** (enforced in review) live in [CLAUDE.md](../CLAUDE.md): routes → domain
services → repositories (routes never touch Mongo directly); the worker reuses the same
repositories; provider types/IDs never leave their adapter; config only via `app/core/config.py`.

## Commands

```bash
uv sync                                         # install
uv run uvicorn app.main:app --reload --port 8000  # API
uv run python -m app.worker                     # worker (delivery / retention / analytics jobs)
uv run pytest                                   # tests
uv run ruff check . && uv run ruff format --check .
uv run mypy app                                 # type gate (app/ only; eval/ excluded)

# Data / content
uv run python scripts/seed_canonical.py         # canonical answers
uv run python scripts/upload_knowledge.py       # push docs/knowledge/ to a Vector Store

# Evaluation (the release gate + dev tool — see docs/EVAL_TESTER_GUIDE.md)
uv run python -m eval.run                        # golden-set gate (spends API $)
uv run python -m eval.run --report r.html --pdf r.pdf   # shareable reports
```

Configuration is centralized in `app/core/config.py` (pydantic-settings). `ENV` defaults to
`prod` (fail-closed); non-dev environments refuse default secrets. Never read `os.environ` elsewhere.
