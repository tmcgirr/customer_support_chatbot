# Cadre AI chatbot backend. Uses the uv base image for reproducible installs.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Install dependencies first (cached until the lockfile changes).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
# Ops scripts (seed_canonical, upload_knowledge, sweep_locks) so a deployed
# container can run them directly (docker compose exec api uv run python scripts/...).
COPY scripts ./scripts

EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
