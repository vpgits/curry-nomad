# Aegra backend (the `nora` graph served over the Agent Protocol).
# Adapted from Aegra's official production Dockerfile for this apps/ monorepo:
# deps + package live in the repo-root pyproject (package at apps/nora/src/nora),
# and aegra.json references ./apps/nora/src. Build context = repo root.
#
#   docker build -t curry-nomad-aegra .
# Usually built via docker-compose.yml (the `aegra` service).

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
COPY pyproject.toml uv.lock ./
RUN uv sync --extra aegra --no-dev --no-install-project --frozen

# 2) The project itself — hatchling builds the `nora` wheel, so it needs the
#    package source and the README referenced by pyproject's `readme = ...`.
COPY apps/nora ./apps/nora
COPY aegra.json README.md ./
RUN uv sync --extra aegra --no-dev --frozen

# -----------------------------
# Runtime: slim image with just the venv + what aegra serve needs at run time
# -----------------------------
FROM base AS final
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
# aegra.json adds ./apps/nora/src to the path (import the graph) and the seed
# script lives under apps/nora/scripts, so carry the package tree along.
COPY apps/nora ./apps/nora
COPY aegra.json ./

ENV PATH="/app/.venv/bin:$PATH" \
    AEGRA_CONFIG=/app/aegra.json \
    HOST=0.0.0.0 \
    PORT=2026

EXPOSE 2026
# aegra serve runs migrations on startup, then uvicorn (no reload). It loads the
# graph via make_graph(), which needs OPENAI_API_KEY in the environment.
CMD ["aegra", "serve"]
