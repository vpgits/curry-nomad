# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A LangGraph / LangChain **1.x** teaching artifact. "Nora" is the operations assistant for a
fictional Sri Lankan spice business. One **orchestrator** routes each request to one of two
capabilities that deliberately contrast:

- **Analytics — an AGENT** (`analytics/`): a hand-written tool loop that writes SQL over a
  bundled SQLite DB and *self-corrects when a query fails*.
- **Marketing Studio — a WORKFLOW** (`marketing/`): a deterministic graph (chaining + parallel
  fan-out + evaluator-optimizer loop) that produces a video-ad brief, with one human-review
  checkpoint.

Because it is a teaching codebase, clarity and the *visibility of the mechanism* are the point —
e.g. the agent loop is spelled out by hand rather than using `create_agent` (the prebuilt
shortcut is preserved in an appendix comment in `analytics/graph.py`). Preserve that intent when
editing: keep patterns explicit and the explanatory docstrings/comments intact.

## Repository layout

Monorepo with two sibling apps under `apps/`:
- `apps/nora/` — the Python backend (package `nora` under `apps/nora/src/nora/`, plus `tests/`,
  `evals/`, `scripts/`).
- `apps/web/` — the Next.js frontend (Agent Protocol client).

It's a **single root Python package**: `pyproject.toml`, `uv.lock`, and the `langgraph.json`
graph config live at the **repo root** — run every command from there. Unless a
path is given from the repo root, file references below are relative to the `nora` package
(`apps/nora/src/nora/`).

## Commands

Python is managed with **uv** (Python 3.12). Run all commands from the repo root.

```bash
uv sync                                          # install deps
uv run python -m nora.data.seed                  # rebuild the bundled SQLite DB (deterministic; only if changing data)
uv run python -m nora.app "What was our best-selling product in Colombo last quarter?"   # run one turn (needs provider key)
uv run python apps/nora/evals/run_evals.py --suite all   # eval suites: analytics | marketing | all (needs provider key)
uv run langgraph dev                             # serve the `nora` graph + LangSmith Studio

uv run pytest                                    # full offline test suite (NO API key needed)
uv run pytest apps/nora/tests/test_analytics_graph.py   # one file
uv run pytest -k recovery                         # one test by name substring
uv run ruff check .                              # lint (line-length 100, ruff config in pyproject.toml)
```

**Tests run fully offline** (no provider key) by injecting scripted fake models — see Testing
below. The **app and evals need a real provider key**; live end-to-end tests are
`@pytest.mark.skipif`-gated on `OPENAI_API_KEY`.

### Provider switch
Every model is built from a `provider:model` string (e.g. `openai:gpt-4o`) via `init_chat_model`
/ `init_embeddings` — **no provider SDK is ever imported directly**. Switch providers by changing
env vars (`NORA_MODEL`, `NORA_ROUTER_MODEL`, `NORA_EMBEDDING_MODEL`) and supplying the matching
key. Anthropic needs `uv sync --extra anthropic` first. The embedding model defaults to OpenAI, so
the semantic Store still needs `OPENAI_API_KEY` even on a non-OpenAI chat model.

### Web stack (optional)
```bash
uv run langgraph dev --allow-blocking            # serve `nora` over the Agent Protocol on :2024 (in-memory; needs OPENAI_API_KEY)
uv run python apps/nora/scripts/seed_store.py    # seed brand voice + metric definitions into the running Store
cd apps/web && npm install && npm run dev        # Next.js chat UI on :3000
```
`--allow-blocking` is required: Nora's nodes invoke their subgraphs synchronously (`.invoke()`) and
analytics uses synchronous SQLite, so the async dev server would otherwise raise `BlockingError`.

## Architecture — the load-bearing ideas

**Orchestrator wraps compiled subgraphs (`orchestrator.py`).** `route → Command(goto=...) →
analytics | marketing | clarify → END`. The two capabilities are **compiled subgraphs invoked
inside the orchestrator's nodes**, and each node passes its `config` straight through on
`.invoke(state, config)`. That pass-through is what makes a HITL `interrupt()` deep inside the
marketing subgraph bubble all the way up and pause the whole orchestrator, and a
`Command(resume=...)` on the same `thread_id` flow back down into it. This single-thread
interrupt/resume is the canonical demo — don't break the `config` plumbing.

**Two compile paths — know which you're touching.**
- `build_orchestrator(...)` / `build_*_graph(...)`: explicit constructors with **injectable**
  `model`, `checkpointer`, `store` (and `spice_db`, `auto_approve`). This is how tests and the CLI
  wire things.
- `make_graph()` (referenced by `langgraph.json`): compiles **without** a checkpointer/store
  because the *platform* (`langgraph dev`) injects persistence + the semantic Store at runtime.
  The CLI (`app.py`) is the self-contained path and builds its own in-memory ones.

**Self-correction loop (`analytics/`).** `run_sql` lets `SqlError` **propagate**;
`ToolNode(handle_tool_errors=handle_sql_error)` turns it into a ToolMessage the model reads and
repairs. `handle_sql_error(error: SqlError)` is annotated so ToolNode catches **only** `SqlError`
— any other exception fails loud. Don't broaden that catch.

**State is TypedDict + reducers (`state.py`).** Reducers: `add_messages` (chat), `operator.add`
(fan-in for parallel ideation), and `reset_or_extend` for `shot_prompts` — it returns `[]` when a
node yields `None`, so the evaluator-optimizer loop can clear stale per-shot prompts before
regenerating on each revision. TypedDict is deliberate (required by the prebuilt agent path and
clean for partial-update semantics) — don't convert state to Pydantic.

**Marketing pipeline shape (`marketing/graph.py`).** `fetch_product → load_brand → ideate(∥) →
choose_concept → write_script → human_review → storyboard → [Send fan-out] shot_prompt_worker(∥)
→ critique → (assemble | revise→storyboard)`. The single HITL gate sits **before** the expensive
creative steps (gate by risk). `critique → revise` loops until pass or `marketing_max_revisions`.
`human_review` returns `Command[Literal["storyboard","cancel"]]`; pass `auto_approve=True` to skip
the interrupt in unattended/eval runs.

**Memory (`memory.py`).** A checkpointer (short-term; makes interrupt/resume work) **and** a
semantic Store (long-term), both compiled in and actually *read in nodes via `runtime.store`* —
not built-and-ignored. Two namespaces: `BRAND` (marketing reads brand voice) and `DEFINITIONS`
(analytics reads metric definitions). Seed data lives in `seed_items()`, loaded two ways: in-process
`seed_brand_knowledge(store)` for the CLI, and `apps/nora/scripts/seed_store.py` over the Store
API for the platform path (`langgraph dev`).

**Config (`config.py`).** `Settings` (pydantic-settings, `NORA_` env prefix) via the cached
`get_settings()` singleton. **Secrets are intentionally NOT Settings fields** — provider keys and
`LANGSMITH_*` are read straight from the environment by the integration packages. `data_as_of` is a
fixed date so time-relative SQL queries are deterministic. The bundled DB path is resolved relative
to the package, not the cwd.

**Ports & adapters (`services/`).** `interfaces.py` defines `SpiceDB` and `Renderer` Protocols; the
graph depends on the shape, so swapping in a real adapter (or renderer via `NORA_RENDERER`) is
wiring-only. Production swaps (Sqlite/Postgres checkpointer, Postgres/Redis store, real renderer)
are config changes, never graph changes.

**Observability (`observability.py`).** Structured `structlog` events with stable keys
(`route.decided`, `sql.run`, `sql.error`, `hitl.raised`, `marketing.revision`, `eval.scored`) — use
the logger, never `print()` (except the human-facing eval report and the demo CLI rendering). Two
optional, env-gated tracers layer on top: **LangSmith** (auto-on via `LANGSMITH_TRACING=true`) and
**Langfuse** (`get_langfuse_handler()`, gated on `LANGFUSE_PUBLIC_KEY`; lazy-imported optional extra
`uv sync --extra langfuse`). Like provider keys, `LANGFUSE_*` is read straight from the environment,
never added to `Settings`. The CLI attaches the Langfuse handler to its run `config` (one attach
point traces the whole orchestrator via the `config` pass-through) and flushes before exit; self-host
the stack with `docker-compose.langfuse.yml` (UI on :3001). The **full web app** traces via
LangSmith instead — `langgraph dev` integrates it natively, so `LANGSMITH_TRACING=true` +
`LANGSMITH_API_KEY` in the env is all the web path needs (no code), grouping runs by thread.

**Running the whole app.** The root `docker-compose.yml` builds + runs the slimmed stack (the
`langgraph dev` backend + one-shot Store `seed` + Next.js `web`; no Postgres): `docker compose up
--build` → the UI on :3000. `Dockerfile` (backend, `langgraph dev`) and `apps/web/Dockerfile`
(Next.js) back it; the web image pins pnpm via `packageManager`. The in-repo alternative is
`langgraph dev` + `pnpm dev`.

## Testing approach

Graphs accept an injected `model=`, and `apps/nora/tests/fakes.py` provides `ScriptedChatModel`
(pops a pre-scripted sequence of AIMessages — script a bad-SQL call then a good one to exercise
self-correction with the *real* ToolNode + DB) and `ScriptedStructuredModel` (returns scripted
objects per Pydantic schema for the marketing workflow). `apps/nora/tests/conftest.py` builds a
disposable seeded DB per session. When adding a graph node or path, add an offline test that drives it with a
fake rather than a live model.

## Specs

Built to `specs/` (read in order): `00_api_contracts.md`, `01_implementation_spec.md`,
`02_data_and_evals.md`, `03_milestones.md`. Higher-level context: `docs/CASE_STUDY_PLAN.md`. The
README's "Teaching map" table maps each concept to its file.
