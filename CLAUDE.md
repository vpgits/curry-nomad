# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A LangGraph / LangChain **1.x** teaching artifact. "Nora" is the operations assistant for a
fictional Sri Lankan spice business. One **orchestrator** routes each request to one of three core
capabilities that deliberately contrast (plus an optional, OFF-by-default fourth, `workspace`):

- **Analytics — an AGENT** (`analytics/`): a hand-written tool loop that writes SQL over a
  bundled SQLite DB and *self-corrects when a query fails*.
- **Marketing Studio — a WORKFLOW** (`marketing/`): a deterministic graph (chaining + parallel
  fan-out + evaluator-optimizer loop) that produces a video-ad brief, with two human-review
  checkpoints (concept pick, then script).
- **Operations / Routing — DETERMINISTIC SERVICES** (`operations/`): a non-agentic backend
  (writable store, business-rule services, an NP-hard delivery-route optimizer) that the
  `routing` capability merely *calls*. This is the deliberate "**limits of agentic development**"
  pillar — the rules live in code, not a prompt, so the agent literally cannot oversell or invent
  a route.
- **Workspace — an AGENT over EXTERNAL tools via MCP** (`workspace/`, *optional, OFF by default*):
  a tool loop (like analytics) that acts on the **logged-in operator's own Google account**
  (Gmail/Calendar) through the self-hosted Google Workspace **MCP** server. The contrast with
  analytics: an agent over a *real external system reached via MCP* and gated by **OAuth**, not an
  in-process DB. Enable with `NORA_WORKSPACE_ENABLED=true` + `uv sync --extra workspace`; see the
  "Workspace capability" architecture note below.

A cross-cutting concern is **native generative UI**: capabilities push typed UI cards over
LangGraph's `push_ui_message` channel (analytics dashboard, marketing storyboard/timeline/critique,
the `route_map`), which the web client renders via `LoadExternalComponent`. There is no CopilotKit —
the chat is `useStream` → Aegra, and the gen-UI is push-based and native.

Because it is a teaching codebase, clarity and the *visibility of the mechanism* are the point —
e.g. the agent loop is spelled out by hand rather than using `create_agent` (the prebuilt
shortcut is preserved in an appendix comment in `analytics/graph.py`). Preserve that intent when
editing: keep patterns explicit and the explanatory docstrings/comments intact.

## Repository layout

Monorepo with two sibling apps under `apps/`:
- `apps/nora/` — the Python backend (package `nora` under `apps/nora/src/nora/`, plus `tests/`,
  `evals/`, `scripts/`). Subpackages: `analytics/` (the agent), `marketing/` (the workflow),
  `operations/` (the deterministic ops backend + REST API), `workspace/` (the optional Google
  Workspace MCP agent), `services/` (ports & adapters), plus `orchestrator.py` (router),
  `auth.py` (the optional Aegra custom-auth handler for per-operator identity), and `a2ui_studio.py`
  (a second graph: the dynamic-schema gen-UI showcase).
- `apps/web/` — the Next.js frontend (Agent Protocol client; renders the native gen-UI cards).

It's a **single root Python package**: `pyproject.toml`, `uv.lock`, and the `aegra.json`
graph config live at the **repo root** — run every command from there. `aegra.json` registers
**two graphs**: `nora` (the orchestrator) and `nora_a2ui` (the studio). Unless a
path is given from the repo root, file references below are relative to the `nora` package
(`apps/nora/src/nora/`).

## Commands

Python is managed with **uv** (Python 3.12). Run all commands from the repo root.

```bash
uv sync                                          # install deps
uv run python -m nora.data.seed                  # rebuild the bundled read-only SQLite DB (deterministic; only if changing data)
uv run python -m nora.operations.seed            # (re)build the WRITABLE operations DB (data/runtime/operations.db; needs --extra operations)
uv run python -m nora.app "What was our best-selling product in Colombo last quarter?"   # run one turn (needs provider key)
uv run python apps/nora/evals/run_evals.py --suite all   # eval suites: analytics | marketing | all (needs provider key)
uv run --extra aegra aegra dev                    # serve the `nora` + `nora_a2ui` graphs over the Agent Protocol (Aegra; starts Postgres via Docker)
uv run --extra operations nora-ops-api            # serve the operations REST API on :8000 (no LLM, no API key)

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

**Reasoning chain (opt-in).** Set `NORA_THINKING_BUDGET` to a token budget (e.g. `2048`) *and* an
Anthropic `NORA_MODEL` (e.g. `anthropic:claude-sonnet-4-6`) to turn on extended thinking for the
analytics agent. Its reasoning streams into the chat as `thinking` content blocks, rendered inline by
the web UI as a collapsible "reasoning" card next to the tool steps (`analytics/graph.py` builds the
model with `thinking=` + `temperature=1`; the frontend pulls it via `getReasoningString`). Default
`0` = off, so the gpt-4o path (which emits no reasoning) is unchanged.

### Web stack (optional)
```bash
uv run --extra aegra aegra dev                    # serve `nora`/`nora_a2ui` over the Agent Protocol on :2026 (Postgres via Docker; needs OPENAI_API_KEY)
uv run --extra operations nora-ops-api            # serve the ops REST API on :8000 (the `routing` capability + /stock /orders /routes call it)
uv run python apps/nora/scripts/seed_store.py    # seed brand voice + metric definitions into the running Store
cd apps/web && pnpm install && pnpm dev          # Next.js UI on :3000
```
Unlike `langgraph dev`, Aegra does not enforce a blocking-call check, so Nora's synchronous
`.invoke()` subgraph calls (and synchronous SQLite) need no special flag. Aegra is Postgres-backed,
so threads/Store persist across restarts. The web app's routes: `/` (home), `/ask` (chat with
inline gen-UI), `/stock` `/orders` `/routes` `/inventory` (operations, fed by the ops API),
`/briefs` (marketing HITL), and `/studio` (the `nora_a2ui` dynamic-schema gen-UI showcase). Routing
asks and the operations pages need the **ops API running** (its absence degrades to a text reply,
never a crash).

## Architecture — the load-bearing ideas

**Orchestrator wraps compiled subgraphs (`orchestrator.py`).** `route → Command(goto=...) →
analytics | marketing | routing | clarify → END`. Analytics is added as a **real subgraph node**
(not invoked imperatively), so its `run_sql` steps and streamed final answer flow live into the
top-level thread and render inline (clients opt in with `streamSubgraphs: true`); it then flows
through an `analytics_dashboard` node that attaches the gen-UI card. Marketing stays an **imperative
function node** (`.invoke(state, config)`) — its config pass-through is what makes a HITL
`interrupt()` deep inside the marketing subgraph bubble all the way up and pause the whole
orchestrator, and a `Command(resume=...)` on the same `thread_id` flow back down into it. This
single-thread interrupt/resume is the canonical demo — don't break the `config` plumbing. `routing`
is a deterministic node (no LLM) that plans a route by calling the ops API (`route_planner`,
injectable for offline tests) and pushes a `route_map` card.

**Two compile paths — know which you're touching.**
- `build_orchestrator(...)` / `build_*_graph(...)`: explicit constructors with **injectable**
  `model`, `checkpointer`, `store` (and `spice_db`, `auto_approve`, `auto_choose`, `route_planner`,
  `dashboard_model`). This is how tests and the CLI wire things.
- `make_graph()` / `make_a2ui_graph()` (referenced by `aegra.json` as `nora` / `nora_a2ui`):
  compile **without** a checkpointer/store because the *platform* (Aegra) injects persistence
  (Postgres checkpointer) + the semantic Store at runtime. The CLI (`app.py`) is the self-contained
  path and builds its own in-memory ones.

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
→ critique → (assemble→render→END | revise→storyboard)`. There are **two** HITL gates, both before
the expensive creative steps (gate by risk): `choose_concept` (the concept-pick gate) and
`human_review` (script review). `critique → revise` loops until pass or `marketing_max_revisions`.
Two knobs control the gates, both defaulting to *skip* so unattended evals/tests keep their single
script gate: `auto_choose=True` auto-picks the first concept (the orchestrator passes
`auto_choose=False` to add the interactive `interrupt()` whose payload carries
`kind: "concept_pick"`); `auto_approve=True` passes `human_review` through (its `interrupt` payload
carries `kind: "script_review"`, and it returns `Command[Literal["storyboard","cancel"]]`). The
finished workflow's artifacts are pushed as gen-UI cards (`video_brief`, `marketing_storyboard`,
`marketing_script_timeline`, `marketing_critique`).

**Operations subsystem (`operations/`).** A deliberately **non-agentic** Phase-1 backend — the
"limits of agentic development" pillar. Layered: `schema.py` (DDL for a *writable* SQLite DB, kept
separate from the read-only bundled one so the committed dataset stays pristine) → `store.py`
(`SqliteOperationsStore`, pure data access + a `tx()` transaction seam, zero business rules) →
`services.py` (the **single source of truth for every business rule**: `create_order` rejects an
oversell, `adjust_stock` can't drive stock below zero, every mutation is one atomic tx + ledger
entry) → `api.py` (a thin FastAPI layer that just calls `services.*`). `routing.py` is a pure,
deterministic delivery-route optimizer (haversine matrix → nearest-neighbor → 2-opt; reports
`naive_km` as the "no planning" baseline) — the agent *calls* it, never guesses a tour. Rejections
raise **`OperationsError`** (the deliberate analogue of `SqlError`): the REST layer turns it into a
structured 4xx; a Phase-2 agent tool would turn it into a ToolMessage to self-correct from. Rebuild
the writable DB deterministically with `python -m nora.operations.seed` (fixed RNG, no wall-clock;
plants a few low-stock SKUs and a zig-zag delivery set so the demos have signal). Like `services/`,
it's **ports & adapters**: `operations/interfaces.py:OperationsStore` is a Protocol, so a Postgres
adapter is wiring-only.

**Workspace capability (`workspace/`, optional — OFF by default).** An agent that acts on the
**logged-in operator's own Google account** (Gmail/Calendar) via the self-hosted Google Workspace
**MCP** server — the contrast with the in-process analytics agent (a tool loop over a *real external
system reached through MCP*, gated by OAuth) and with deterministic `routing`. Gated by
`settings.workspace_enabled` so the **base install never imports `langchain-mcp-adapters`** and the
offline suite stays green; the orchestrator wires a stub "connect" node when off. It's an **imperative
orchestrator node** (like `marketing`, not a compiled subgraph node like `analytics`) because the
tool set is **per-run, token-dependent**: `build_workspace_agent(...)`'s injectable `tools_provider`
(the analogue of routing's `route_planner`) mints a **fresh `MultiServerMCPClient` per run** with the
operator's bearer token in the headers — the documented dodge for `langchain-mcp-adapters`' lack of
per-request token swapping. Errors mirror analytics: a narrow `handle_workspace_error(ToolException)`
becomes a ToolMessage for self-correction (don't broaden the catch). **Two auth planes, kept
separate:** *identity* (Plane 1) is per-operator — Aegra `AUTH_TYPE=custom` + `auth.py` verifies the
NextAuth-minted HS256 session JWT (`NEXTAUTH_SECRET`, never a `Settings` field) so threads scope per
user; *authorization* (Plane 2) is a **separate, incremental** Google grant (the web app's
`/api/google/{connect,callback,token,status}`), and the access token rides **per-run in
`config.configurable.google_access_token`** (read in `orchestrator.py:workspace`; a `# TODO(prod)`
notes that this lands in checkpoints — production would carry it as a JWT claim instead). Demo-only:
publish the Google OAuth app in **Testing** mode (≤100 test users; refresh tokens expire in 7 days, so
token storage is just a session-scoped encrypted cookie). Run it with `uv sync --extra workspace`,
`NORA_WORKSPACE_ENABLED=true`, `AUTH_TYPE=custom`, and `docker compose --profile workspace up`.

**Generative UI is native and push-based (`push_ui_message`).** Capabilities attach typed UI cards
by calling `push_ui_message("<name>", payload, message=...)`; the web client renders them via
`LoadExternalComponent` (no CopilotKit). Cards: `analytics_dashboard` (composed post-hoc by a
`dashboard_model` from the agent's answer + the SQL it ran — see `_build_dashboard`), the marketing
set (`video_brief` / `marketing_storyboard` / `marketing_script_timeline` / `marketing_critique` /
`marketing_render`), and `route_map` (rendered as a Leaflet map). **Gen-UI is always best-effort** — it's wrapped so a
failure (or no provider key offline) skips the card and never blocks the text answer. Internal
`with_structured_output` calls that build cards (router, dashboard, marketing) use
`disable_streaming=True` so their tool-call deltas don't surface as phantom partial messages on
Aegra's `messages` stream; only the analytics agent streams (its tokens *are* the answer).

**Marketing rendering — real media via OpenRouter (`services/renderer.py`, `services/openrouter.py`).**
Placeholder by default (`NORA_RENDERER=placeholder`, no spend, no key); `NORA_RENDERER=openrouter`
swaps in the real adapter behind the `Renderer` port (the ports-&-adapters payoff). It generates a
hero image + a still per shot **synchronously** via OpenRouter `/images`, then submits one
**image→video** job per shot via `/videos` and returns the job ids in `render_result` — the render
node never blocks on the slow video; the `marketing_render` card polls each job from the UI. Stills
are written to `settings.media_dir` and served by the **ops-api at `/media`** (keyless static files,
on a dir/volume shared with the renderer); video status + content are proxied by Next.js
`app/api/render/video/[jobId]` so the OpenRouter key stays server-side. **Image→video needs a public
first-frame URL** OpenRouter can fetch (`NORA_MEDIA_PUBLIC_BASE_URL`) — `localhost`/base64 won't do;
without it the renderer falls back to text→video (recorded in `render_result.mode`). The OpenRouter
HTTP client is **injectable**, so the renderer's tests run fully offline against a fake.

**A2UI studio — the dynamic-schema contrast (`a2ui_studio.py`, graph `nora_a2ui`).** Where the
analytics path attaches a *fixed* dashboard shape, this graph (`analytics → ui_author`) lets a
"UI-author" model **compose** the surface from an ordered list of catalog blocks (`A2uiSurface` /
`A2uiBlock` in `schemas.py`) — the "LLM authors the UI" pattern, rendered by the `/studio` web
surface. Note `A2uiBlock` is deliberately **one flat model with optional per-type fields, not a
discriminated union** — OpenAI strict structured-output rejects `anyOf`/`oneOf`, so a union would
make the authoring call throw. Same lesson constrains `AnalyticsDashboard`.

**Memory (`memory.py`).** A checkpointer (short-term; makes interrupt/resume work) **and** a
semantic Store (long-term), both compiled in and actually *read in nodes via `runtime.store`* —
not built-and-ignored. Two namespaces: `BRAND` (marketing reads brand voice) and `DEFINITIONS`
(analytics reads metric definitions). Seed data lives in `seed_items()`, loaded two ways: in-process
`seed_brand_knowledge(store)` for the CLI, and `apps/nora/scripts/seed_store.py` over the Store
API for the platform path (Aegra).

**Config (`config.py`).** `Settings` (pydantic-settings, `NORA_` env prefix) via the cached
`get_settings()` singleton. **Secrets are intentionally NOT Settings fields** — provider keys and
`LANGSMITH_*` are read straight from the environment by the integration packages. `data_as_of` is a
fixed date so time-relative SQL queries are deterministic. Both DB paths (`db_path` read-only,
`ops_db_path` writable) resolve relative to the package, not the cwd. The routing capability finds
the ops service via `ops_api_url` (default `http://localhost:8000`); `marketing_num_concepts` sets
the parallel-ideation count.

**Ports & adapters (`services/`, `operations/`).** `services/interfaces.py` defines `SpiceDB` and
`Renderer` Protocols, and `operations/interfaces.py` the read-write `OperationsStore`; everything
depends on the *shape*, so swapping in a real adapter (a Postgres store, a renderer via
`NORA_RENDERER`) is wiring-only. Production swaps (Sqlite/Postgres checkpointer, Postgres/Redis
store, real renderer) are config changes, never graph changes.

**Observability (`observability.py`).** Structured `structlog` events with stable keys
(`route.decided`, `sql.run`, `sql.error`, `hitl.raised`, `marketing.revision`, `routing.planned`,
`dashboard.built`, `eval.scored`) — use the logger, never `print()` (except the human-facing eval
report and the demo CLI rendering). Two
optional, env-gated tracers layer on top: **LangSmith** (auto-on via `LANGSMITH_TRACING=true`) and
**Langfuse** (`get_langfuse_handler()`, gated on `LANGFUSE_PUBLIC_KEY`; lazy-imported optional extra
`uv sync --extra langfuse`). Like provider keys, `LANGFUSE_*` is read straight from the environment,
never added to `Settings`. The CLI attaches the Langfuse handler to its run `config` (one attach
point traces the whole orchestrator via the `config` pass-through) and flushes before exit; self-host
the stack with `docker-compose.langfuse.yml` (UI on :3001). The **full web app** traces via
Aegra's OpenTelemetry instrumentation — set `OTEL_TARGETS=LANGFUSE` + `LANGFUSE_BASE_URL` (or any
OTLP backend) and runs group by thread in the Sessions view; `LANGSMITH_TRACING=true` still works
at the LangChain level.

**Running the whole app.** The root `docker-compose.yml` builds + runs the stack (Postgres + the
`aegra` (Aegra `serve`) backend + one-shot Store `seed` + the `ops-api` operations service + Next.js
`web`): `docker compose up --build` → chat at :3000, inventory at :3000/inventory. The `ops-api`
service reuses the backend image (built with `--extra operations`), seeds its writable ephemeral
SQLite on start, and serves the operations REST API on :8000 — no LLM, so no API key. `Dockerfile`
(backend, `aegra serve`) and `apps/web/Dockerfile` (Next.js) back it; the web image pins pnpm via
`packageManager`. The in-repo alternative is `aegra dev` + `uvicorn nora.operations.api:app`
+ `pnpm dev`.

## Testing approach

Graphs accept an injected `model=`, and `apps/nora/tests/fakes.py` provides `ScriptedChatModel`
(pops a pre-scripted sequence of AIMessages — script a bad-SQL call then a good one to exercise
self-correction with the *real* ToolNode + DB) and `ScriptedStructuredModel` (returns scripted
objects per Pydantic schema for the marketing workflow). `apps/nora/tests/conftest.py` builds a
disposable seeded DB per session. When adding a graph node or path, add an offline test that drives it with a
fake rather than a live model. The **operations layer needs no fakes** — it's deterministic, so its
tests (`test_operations_*`) drive the real services/optimizer/API against a disposable writable DB;
the gen-UI push (`push_ui_message` payloads) is covered by `test_generative_ui.py`.

## Specs

Built to `specs/` (read in order): `00_api_contracts.md`, `01_implementation_spec.md`,
`02_data_and_evals.md`, `03_milestones.md`. Higher-level context: `docs/CASE_STUDY_PLAN.md`. The
README's "Teaching map" table maps each concept to its file.
