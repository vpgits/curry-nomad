# Backend image: the `nora` graph served over the Agent Protocol by Aegra (`aegra serve`).
# Deps + package live in the repo-root pyproject (package at apps/nora/src/nora), and
# aegra.json references ./apps/nora/src. Build context = repo root.
#
#   docker build -t curry-nomad-aegra .
# Usually built via docker-compose.yml (the `aegra` service).
#
# The same image also serves the deterministic operations REST API (the `ops-api` compose
# service reuses it with a different command), so it's built with the `operations` extra too.

FROM python:3.12-slim-bookworm AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# -----------------------------
# Builder: resolve + install deps, then the project, into /app/.venv
# -----------------------------
FROM base AS builder
COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# 1) Dependencies only (cached layer) — needs just the manifests + lockfile.
#    `--extra aegra` installs aegra-cli (the server); `--extra operations` adds fastapi/uvicorn so
#    this one image can ALSO serve the operations REST API. --no-dev: the server needs no pytest/ruff.
COPY pyproject.toml uv.lock ./
RUN uv sync --no-install-project --frozen --no-dev --extra aegra --extra operations

# 2) The project itself — hatchling builds the `nora` wheel, so it needs the
#    package source and the README referenced by pyproject's `readme = ...`.
COPY apps/nora ./apps/nora
COPY aegra.json README.md ./
RUN uv sync --frozen --no-dev --extra aegra --extra operations

# -----------------------------
# Runtime: slim image with the venv + what `aegra serve` needs at run time
# -----------------------------
FROM base AS final
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
# aegra.json adds ./apps/nora/src to the path (import the graph) and the seed script lives
# under apps/nora/scripts, so carry the package tree along.
COPY apps/nora ./apps/nora
COPY aegra.json ./

ENV PATH="/app/.venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=2026

EXPOSE 2026
# `aegra serve` applies DB migrations on startup, then runs uvicorn (no reload). It loads the graph
# via make_graph(), which needs OPENAI_API_KEY in the environment (chat models + the semantic Store
# embeddings) and a reachable Postgres (DATABASE_URL / POSTGRES_*).
CMD ["aegra", "serve", "--host", "0.0.0.0", "--port", "2026"]
