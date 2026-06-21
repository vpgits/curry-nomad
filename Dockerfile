# Backend image: the `nora` graph served over the Agent Protocol by `langgraph dev`.
# Deps + package live in the repo-root pyproject (package at apps/nora/src/nora), and
# langgraph.json references "." (the repo). Build context = repo root.
#
#   docker build -t curry-nomad-backend .
# Usually built via docker-compose.yml (the `backend` service).
#
# NOTE: `langgraph dev` is the in-memory LangGraph CLI server (no Postgres; state is
# ephemeral). It's a dev-grade server, so this image deliberately keeps the `dev`
# dependency group (which provides `langgraph-cli[inmem]`).

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
    build-essential \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# 1) Dependencies only (cached layer) — needs just the manifests + lockfile.
#    Keep the dev group so `langgraph-cli[inmem]` (which powers `langgraph dev`) is installed.
#    `--extra operations` adds fastapi/uvicorn so this one image can ALSO serve the operations
#    REST API — the `ops-api` compose service reuses this image with a different command.
COPY pyproject.toml uv.lock ./
RUN uv sync --no-install-project --frozen --extra operations

# 2) The project itself — hatchling builds the `nora` wheel, so it needs the
#    package source and the README referenced by pyproject's `readme = ...`.
COPY apps/nora ./apps/nora
COPY langgraph.json README.md ./
RUN uv sync --frozen --extra operations

# -----------------------------
# Runtime: slim image with the venv + what `langgraph dev` needs at run time
# -----------------------------
FROM base AS final
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
# langgraph.json adds "." to the path (import the graph) and the seed script lives
# under apps/nora/scripts, so carry the package tree along.
COPY apps/nora ./apps/nora
COPY langgraph.json ./

ENV PATH="/app/.venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=2024

EXPOSE 2024
# `langgraph dev` loads the graph via make_graph(), which needs OPENAI_API_KEY in the
# environment (chat models + the semantic Store embeddings). --no-browser keeps it headless.
# --allow-blocking: Nora's nodes call subgraphs with synchronous .invoke() and analytics uses
# synchronous SQLite; the async dev server would otherwise raise BlockingError on the event loop.
CMD ["langgraph", "dev", "--host", "0.0.0.0", "--port", "2024", "--no-browser", "--allow-blocking"]
