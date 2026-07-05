# Curry Nomad — an agentic workflows case study

A clean, runnable **LangGraph / LangChain 1.x** application built as a teaching artifact: the
reference codebase for a ~90-minute hands-on session on how to build agentic systems properly.
It shows the agent and workflow paradigms side by side under one orchestrator — with a
deterministic, non-agentic operations backend as the counterpoint — plus the production concerns
that make any of them trustworthy: tools, human-in-the-loop, memory, generative UI, observability,
and evaluation.

**Nora** is the operations assistant for **Curry Nomad**, a fictional Sri Lankan spice business.
One orchestrator routes each request to one of three core capabilities that deliberately contrast
(plus an optional, OFF-by-default fourth, **Workspace**):

- **Analytics — an AGENT.** Answers questions over a bundled SQLite database: writes SQL, runs
  it, and *self-corrects when a query fails*. Open-ended, so it's a hand-built tool loop.
- **Marketing Studio — a WORKFLOW.** Generates an image **Instagram post** for a product via a
  predictable pipeline with human-review checkpoints (concept pick, copy, then the generated
  stills). Predictable, so it's a deterministic graph: chaining + parallel fan-out + an
  evaluator-optimizer loop.
- **Operations / Routing — DETERMINISTIC SERVICES.** Inventory, orders, and an NP-hard delivery-route
  optimizer, behind a REST API the agent merely *calls*. The "**limits of agentic development**"
  pillar — the rules live in code, not a prompt, so the agent can't oversell or invent a route.
- **Workspace — an AGENT over EXTERNAL tools via MCP** *(optional, OFF by default).* Acts on the
  logged-in operator's **own Google account** (Gmail/Calendar) through the self-hosted Google
  Workspace **MCP** server — an agent over a *real external system*, gated by **OAuth**. Enable with
  `NORA_WORKSPACE_ENABLED=true` + `uv sync --extra workspace`; see CLAUDE.md for the two-plane auth
  model (per-operator identity + a separate incremental Workspace grant).

Each capability surfaces its result as **native generative UI**: typed cards pushed over LangGraph's
`push_ui_message` channel (an analytics dashboard, the marketing storyboard/timeline/critique, a
Leaflet `route_map`) and rendered by the web client via `LoadExternalComponent` — no CopilotKit.

**Canonical demo:** *"What's our best-selling product in Colombo last quarter?"* → the analytics
agent answers (self-correcting a bad query, with a dashboard card) → *"Make an Instagram post for it"* →
the marketing workflow runs, pauses for you to pick a concept, approve the copy, and approve the
generated stills, then finishes — all on one thread.

## Quickstart

```bash
uv sync                                   # installs deps + Python 3.12
cp .env.example .env                       # then add a provider key (see below)
uv run python -m nora.data.seed            # build the bundled SQLite DB (deterministic)
uv run python -m nora.app "What was our best-selling product in Colombo last quarter?"
uv run python apps/nora/evals/run_evals.py --suite all
uv run --extra aegra aegra dev               # optional: serve the graph over the Agent Protocol (Aegra; starts Postgres via Docker)
```

The bundled database is committed, so the seed step is only needed if you want to rebuild it
(it reproduces byte-for-byte). Running the app and the evals needs a provider key; the tests do
not (see [Testing](#testing)).

### Web UI (Next.js)

Beyond the CLI and LangGraph Studio, there's a browser chat UI. It talks to the `nora` graph
over the **Agent Protocol** served by **Aegra** (a self-hosted Agent Protocol backend),
using the official `@langchain/langgraph-sdk`:

```
Next.js (useStream) ──Agent Protocol──▶ Aegra ──▶ nora orchestrator graph
```

Aegra serves the graph (registered in `aegra.json` via the `make_graph` factory) and provides a
**Postgres-backed** checkpointer + semantic Store at runtime, so HITL interrupts persist and
resume, the store propagates into the analytics/marketing subgraphs, and state is **durable
across restarts** (it lives in Postgres). The graph code is unchanged — that's the point of the
Agent Protocol.

**Option A — the whole app in one command (Docker).** Builds and runs the `Aegra + Postgres`
backend + the Next.js UI, and seeds the Store automatically:

```bash
cp .env.example .env          # add OPENAI_API_KEY (the backend won't boot without it)
docker compose up --build     # → open http://localhost:3000
```

The browser hits the UI on `:3000`, which streams from Aegra on `:2026`; the one-shot
`seed` service loads brand voice + metric definitions once the API is healthy. `docker compose
down` stops it.

**Option B — local dev (hot reload).** The app processes run locally:

```bash
# Backend (repo root) — needs OPENAI_API_KEY:
uv run --extra aegra aegra dev                   # serves nora on http://localhost:2026 (starts Postgres via Docker)
uv run python apps/nora/scripts/seed_store.py   # seed brand voice + metric definitions into the store

# Frontend:
cd apps/web && cp .env.example .env.local && pnpm install && pnpm dev    # http://localhost:3000
```

The UI streams Nora's answers and renders the native **generative-UI cards** pushed from the graph
via `LoadExternalComponent`: an analytics **dashboard**, the marketing **concept-pick** and
**copy-approval** gates plus the final storyboard / critique, and a Leaflet
**route map**. Dedicated operations pages (`/stock`, `/orders`, `/routes`, `/inventory`) read the
ops REST API, and an **Author UI** toggle on `/ask` shows the dynamic-schema "LLM authors the UI" mode. See
[`apps/web/`](apps/web/) for details.

### Provider switch (one line)

Every model is built from a `provider:model` config string via `init_chat_model` /
`init_embeddings` — no provider SDK is imported directly. Switch providers in `.env`:

```bash
# Default (OpenAI):
NORA_MODEL=openai:gpt-4o
NORA_ROUTER_MODEL=openai:gpt-4o-mini

# Anthropic (run `uv sync --extra anthropic` once):
NORA_MODEL=anthropic:claude-sonnet-4-6
```

Set the matching key (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …). Note the embedding model
(`NORA_EMBEDDING_MODEL`) defaults to OpenAI, so an `OPENAI_API_KEY` is still needed for the
semantic Store even when the chat model is Anthropic — or point it at another provider.

## Teaching map (concept → file → demo segment)

| Concept / pattern | Where it lives | Session segment |
|---|---|---|
| Provider-agnostic model layer | `config.py`, `init_chat_model` everywhere | Framing (0:00–0:12) |
| **Agent loop + self-correction** | `analytics/graph.py`, `analytics/tools.py` | Analytics agent (0:12–0:35) |
| Safe tools (SELECT-only, LIMIT, timeout) | `services/spice_db.py` | Analytics agent |
| **Prompt chaining + parallel fan-out (`Send`)** | `marketing/graph.py`, `marketing/nodes.py` | Marketing workflow (0:35–0:55) |
| **Evaluator-optimizer loop** | `marketing` `critique` → `revise` | Marketing workflow |
| **Request routing (orchestrator)** | `orchestrator.py` (`route` → analytics / marketing / routing / clarify) | Orchestrator + HITL (0:55–1:05) |
| **Human-in-the-loop (`interrupt`)** | `marketing` `choose_concept` + `human_review` + `still_review` (three gates) | Orchestrator + HITL |
| **Memory: checkpointer + semantic Store** | `memory.py`, read via `runtime.store` in both | Orchestrator + HITL |
| **Limits of agentic dev — deterministic services** | `operations/services.py` (business rules), `operations/api.py` | Operations |
| **NP-hard delivery routing (no LLM)** | `operations/routing.py` (nearest-neighbor + 2-opt) | Operations |
| **Agent over external tools (MCP) + OAuth** *(optional)* | `workspace/graph.py`, `auth.py`, web `app/api/google/*` | Workspace |
| **Native generative UI (`push_ui_message`)** | `orchestrator.py` / `marketing` cards → web `LoadExternalComponent` | Generative UI |
| **Dynamic-schema UI (LLM authors the UI)** | `orchestrator.py` `_author_surface`, `schemas.py` `A2uiSurface`, web "Author UI" toggle on `/ask` | Generative UI |
| **Observability (structlog + LangSmith / Langfuse)** | `observability.py`, `docker-compose.langfuse.yml` | Observability + evals (1:05–1:25) |
| **Evaluation (deterministic + LLM-judge)** | `evals/` | Observability + evals |
| Ports & adapters, reliability | `services/`, `operations/interfaces.py`, `tenacity`, typed `SqlError` / `OperationsError` | Extensibility (1:25–1:30) |

## How the pieces work

**Analytics agent (`analytics/graph.py`).** The loop is hand-written so it's visible:
`START → llm → should_continue → (tools | END)`, with `tools → llm` looping back. A failed
`run_sql` raises `SqlError`; `ToolNode(handle_tool_errors=handle_sql_error)` turns it into a
ToolMessage (the DB error), so the model reads it, fixes the query, and retries. The error
handler is annotated `(error: SqlError)`, so only SQL errors are caught — real bugs still fail
loud. The production shortcut (`create_agent`) is shown in an appendix comment.

**Marketing workflow (`marketing/graph.py`).** A deterministic subgraph:
`fetch_product → load_brand → ideate∥ → choose_concept → write_copy → human_review → storyboard
→ shot_prompt_worker∥ → critique → (assemble → render_stills → still_review → finalize_post |
revise)`. It produces an image **Instagram post** (hero + per-shot stills). Concept ideation runs in
parallel within a node; per-shot prompts fan out with `Send` and gather via a reducer; `critique →
revise` loops until it passes or hits `marketing_max_revisions`. **Three** HITL gates gate by risk:
`choose_concept` (pick from the parallel ideas), `human_review` (approve / edit / reject the copy),
and the visual `still_review` (approve / re-roll the generated stills before the post is finalized).
All are skipped in eval/test mode (`auto_choose` / `auto_approve` / `auto_approve_stills`).

**Operations & delivery routing (`operations/`).** The non-agentic counterpoint — the "limits of
agentic development" made structural. A writable SQLite store, business-rule services
(`create_order` rejects an oversell, every mutation is one atomic transaction + ledger entry), and a
thin FastAPI layer. `routing.py` is a deterministic delivery-route optimizer (haversine →
nearest-neighbor → 2-opt) the agent *calls* rather than guessing a tour. Rejections raise
`OperationsError` — the deliberate analogue of the analytics agent's `SqlError`.

**Generative UI (native `push_ui_message`).** Each capability attaches typed UI cards to its final
message; the web client renders them with `LoadExternalComponent` (no CopilotKit). The analytics
dashboard is composed by a model from the answer + the SQL it ran; an **Author UI** output mode on
`/ask` (`config.configurable.ui_mode == "authored"`) goes further and lets a model *author* the
surface from a block catalog (the `a2ui_surface` card). Gen-UI is always best-effort — a failure
skips the card, never the text answer.

**Memory (`memory.py`).** A checkpointer (short-term, makes interrupt/resume work) and a semantic
Store (long-term). Both are compiled into the graph and actually read in nodes via `runtime.store`:
analytics pulls metric **definitions**, marketing pulls **brand voice**.

**Observability (`observability.py`).** Structured `structlog` events with consistent keys
(`route.decided`, `sql.run`, `sql.error`, `hitl.raised`, `marketing.revision`, `routing.planned`,
`dashboard.built`, `eval.scored`), never `print()`. Two optional, env-gated tracers sit on top: **LangSmith** turns on automatically
when `LANGSMITH_TRACING=true`; **Langfuse** attaches a LangChain `CallbackHandler` in the CLI
(`get_langfuse_handler()`, gated on `LANGFUSE_PUBLIC_KEY`) — one attach point, because the
orchestrator passes the same `config` into both subgraphs, so the whole turn (router → analytics
agent → marketing workflow) lands in one trace. Both are no-ops when unconfigured.

**Self-host Langfuse & trace the CLI demo.** No cloud signup — run the stack locally:

```bash
docker compose -f docker-compose.langfuse.yml up -d   # web, worker, postgres, clickhouse, redis, minio
# open http://localhost:3001  (port 3001 because the Next.js UI owns 3000; org/project/keys are
# auto-created on first boot via LANGFUSE_INIT_*)
uv sync --extra langfuse                                # install the optional tracer
# in .env, uncomment the LANGFUSE_* block (keys already match the compose headless-init values)
uv run python -m nora.app "What was our best-selling product in Colombo last quarter?"
# then open http://localhost:3001 → Traces to see the `nora-turn` trace (models, tokens, spans)
```

The CLI flushes Langfuse before exit, so the short-lived process doesn't drop the trace.

**Tracing the full web app** uses **Aegra's OpenTelemetry instrumentation** — set
`OTEL_TARGETS=LANGFUSE` + `LANGFUSE_BASE_URL` (or point it at any OTLP backend: Langfuse, Phoenix,
…) and runs group by thread in the Sessions view. (LangSmith via `LANGSMITH_TRACING=true` still
works at the LangChain level. The Langfuse CallbackHandler path above is wired for the CLI demo.)

**Evaluation (`evals/`).** Two styles, on purpose. Analytics is graded against ground truth
*derived from the data itself* (run the item's `reference_sql`) plus a trajectory recovery metric.
Marketing is graded with deterministic guardrails (duration, shot counts, hook, CTA, product
grounding, banned claims) plus an LLM-as-judge rubric. The HITL gate is auto-approved in eval mode.

## Project layout

Monorepo: two sibling apps under `apps/`. The Python side is a single root package — its
`pyproject.toml` / `uv.lock` and the `aegra.json` graph config live at the repo root; all
commands run from there.

```
apps/
  nora/                       the Python backend (package `nora`)
    src/nora/
      config.py            settings (pydantic-settings); model strings; data_as_of
      observability.py     structlog setup + event helpers
      schemas.py           Pydantic LLM contracts + Context dataclass
      state.py             TypedDict graph states + reducers
      memory.py            build_store / build_checkpointer / seed_brand_knowledge
      orchestrator.py      the supervisor graph (entry point) + make_graph for Aegra
      app.py               demo CLI (streams a turn, prompts on HITL)
      analytics/           tools.py · prompts.py · graph.py   (the AGENT)
      marketing/           prompts.py · nodes.py · graph.py   (the WORKFLOW)
      operations/          schema · store · services · routing · api · seed   (DETERMINISTIC)
      services/            interfaces.py (ports) · spice_db.py · renderer.py
      data/                seed.py + the committed curry_nomad.db (+ runtime/ writable ops DB)
    evals/                 datasets (.jsonl) · evaluators.py · run_evals.py
    tests/                 offline tests (fakes drive every graph without an API key)
    scripts/               seed_store.py (seed the platform Store over the API)
  web/                      Next.js chat UI (Agent Protocol client)
docs/  specs/              case-study plan + build specs (read in order)
pyproject.toml  uv.lock    single root Python package
aegra.json                 graph + serving config (Aegra; registers the nora graph)
```

## Testing

```bash
uv run pytest        # offline: scripted fake models drive every graph (no API key needed)
uv run ruff check .  # lint
```

The whole suite runs without a provider key by injecting fake models — the SQL self-correction
loop, the marketing workflow, HITL pause/resume, request routing, the generative-UI push, and the
eval harness are all exercised offline. The operations layer needs no fakes (it's deterministic):
its services, the route optimizer, and the REST API are tested directly against a disposable
writable DB. A handful of `@pytest.mark.skipif` tests run live end-to-end when `OPENAI_API_KEY` is set.

## Production swaps (the "you'd change one line" coda)

- **Renderer:** `PlaceholderRenderer` (default, no external calls) ↔ the real `OpenRouterRenderer`
  (`services/renderer.py` — generates a hero image + per-shot stills via OpenRouter `/images`, shown
  in the `marketing_render` card) via `NORA_RENDERER=openrouter` + `OPENROUTER_API_KEY`.
- **Checkpointer:** `InMemorySaver` → `SqliteSaver` / `PostgresSaver` (`langgraph.checkpoint.*`).
- **Store:** `InMemoryStore` → `PostgresStore` / `RedisStore`.
- **Operations store:** `SqliteOperationsStore` → a `PostgresOperationsStore` implementing the same
  `operations/interfaces.py:OperationsStore` Protocol.

These are wiring changes only — no graph changes — which is the ports-&-adapters lesson.

## Specs

Built to the specs in [`specs/`](specs/) (read in order): API contracts, implementation spec,
data & evals, and milestones. Higher-level context is in
[`docs/CASE_STUDY_PLAN.md`](docs/CASE_STUDY_PLAN.md).

Stack: LangGraph 1.x · LangChain 1.x · Python 3.12 (uv) · pydantic / pydantic-settings ·
structlog · tenacity · SQLite · FastAPI / uvicorn (operations API) · Next.js (web) · Aegra
(serving) · pytest · ruff. No secrets in code; `.env` only (the DB seed is intentionally committed).
