# Curry Nomad — native (non-Docker) dev runner.
#
# Runs the local stack directly with uv + pnpm instead of `docker compose up`. Two ways to drive it:
#   • all-in-one:   make dev                              # ops-api + backend + web together; Ctrl-C stops all
#   • per-service:  make ops-api | make backend | make web   # one per terminal (full TTY output)
#
# Wiring:  web :3000  ──►  backend / Aegra :2026  ──►  ops-api :8000
# The web app's defaults (apps/web/lib/config.ts) already point at :2026 and :8000, so it needs no
# env file for local dev. The BACKEND reads .env for OPENAI_API_KEY (chat models + Store embeddings).
#
# Prerequisites:  uv, pnpm (or corepack), and — for `make backend` — Docker.
# DOCKER CAVEAT: `aegra dev` auto-starts a Postgres container (pgvector) for its checkpointer +
# semantic Store. That is the one Docker dependency in this "native" path. To go FULLY Docker-free,
# run your own Postgres and use `make backend-serve` (reads DATABASE_URL — see .env.example).

SHELL := /bin/bash

# uv extras for the local dev stack: `aegra` = the backend graph server, `operations` = the ops API.
EXTRAS := --extra aegra --extra operations
WEB    := apps/web

.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "Curry Nomad — native dev (no docker compose). Targets:"
	@echo
	@echo "  Setup (run once):"
	@echo "    make setup         uv sync (+extras), pnpm install, build the writable ops DB, ensure .env"
	@echo
	@echo "  All-in-one:"
	@echo "    make dev           run ops-api + backend + web together (Ctrl-C stops all)"
	@echo
	@echo "  Per-service (each in its own terminal — full TTY output):"
	@echo "    make ops-api       operations REST API on :8000  (no API key)"
	@echo "    make backend       Aegra serving the nora graph on :2026  (needs OPENAI_API_KEY; starts Postgres via Docker)"
	@echo "    make web           Next.js UI on :3000"
	@echo "    make backend-serve Docker-free backend: aegra serve against your own DATABASE_URL"
	@echo "    make seed-store    seed brand voice + metric defs into the running Store (once, backend must be up)"
	@echo
	@echo "  Data / quality:"
	@echo "    make seed          (re)build the writable operations DB (data/runtime/operations.db)"
	@echo "    make seed-data     rebuild the read-only business DB (only if you changed the dataset)"
	@echo "    make test          uv run pytest (offline; no API key)"
	@echo "    make lint          uv run ruff check ."
	@echo "    make clean         remove the writable ops DB"

# --- setup -------------------------------------------------------------------
.PHONY: setup
setup: .env
	uv sync $(EXTRAS)
	cd $(WEB) && pnpm install
	$(MAKE) seed
	@echo ">> Setup done. Set OPENAI_API_KEY in .env, then 'make dev' (or run the per-service targets)."

# Seed .env from the example on first run; the backend reads it for OPENAI_API_KEY etc.
.env:
	@cp .env.example .env
	@echo ">> Created .env from .env.example — set OPENAI_API_KEY before 'make backend'."

# --- per-service -------------------------------------------------------------
.PHONY: ops-api backend backend-serve web seed-store
ops-api:
	uv run --extra operations nora-ops-api

backend:
	uv run --extra aegra aegra dev

# Fully Docker-free backend: serve against an external Postgres (set DATABASE_URL in .env).
backend-serve:
	uv run --extra aegra aegra serve

web:
	cd $(WEB) && pnpm dev

# Loads brand voice + metric definitions into the live Aegra Store (the backend must be running).
seed-store:
	uv run python apps/nora/scripts/seed_store.py

# --- all-in-one --------------------------------------------------------------
# Launch the three services in the background with prefixed, interleaved logs; a trap tears the
# whole process group down on Ctrl-C so no orphan servers linger. Leading `-` ignores the signal
# exit so make doesn't print a spurious error on shutdown.
.PHONY: dev
dev:
	@echo ">> ops-api :8000 · backend :2026 · web :3000 — Ctrl-C stops all"
	@echo ">> (after the backend is up, run 'make seed-store' once to load brand/metric knowledge)"
	-@trap 'kill 0' EXIT INT TERM; \
	( uv run --extra operations nora-ops-api 2>&1 | while IFS= read -r l; do printf '[ops] %s\n' "$$l"; done ) & \
	( uv run --extra aegra aegra dev         2>&1 | while IFS= read -r l; do printf '[api] %s\n' "$$l"; done ) & \
	( cd $(WEB) && pnpm dev                  2>&1 | while IFS= read -r l; do printf '[web] %s\n' "$$l"; done ) & \
	wait

# --- data / quality ----------------------------------------------------------
.PHONY: seed seed-data test lint clean
seed:
	uv run --extra operations python -m nora.operations.seed

seed-data:
	uv run python -m nora.data.seed

test:
	uv run pytest

lint:
	uv run ruff check .

clean:
	rm -f apps/nora/src/nora/data/runtime/operations.db
