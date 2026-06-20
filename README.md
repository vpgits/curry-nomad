# Curry Nomad — an agentic workflows case study

A clean, runnable **LangGraph / LangChain 1.x** application built as a teaching artifact: the
reference codebase for a ~90-minute hands-on session on how to build agentic systems properly.
It shows the two paradigms side by side under one orchestrator, plus the production concerns
that make either one trustworthy: tools, human-in-the-loop, memory, observability, and evaluation.

**Nora** is the operations assistant for **Curry Nomad**, a fictional Sri Lankan spice business.
One orchestrator routes each request to one of two capabilities:

- **Analytics — an AGENT.** Answers questions over a bundled SQLite database: writes SQL, runs
  it, and *self-corrects when a query fails*. Open-ended, so it's a hand-built tool loop.
- **Marketing Studio — a WORKFLOW.** Generates a structured video-ad brief for a product via a
  predictable pipeline with a human-review checkpoint. Predictable, so it's a deterministic
  graph: chaining + parallel fan-out + an evaluator-optimizer loop.

**Canonical demo:** *"What's our best-selling product in Colombo last quarter?"* → the analytics
agent answers (self-correcting a bad query) → *"Make a 30s video ad for it"* → the marketing
workflow runs, pauses for you to approve the script, then finishes — all on one thread.

## Quickstart

```bash
uv sync                                   # installs deps + Python 3.12
cp .env.example .env                       # then add a provider key (see below)
uv run python -m nora.data.seed            # build the bundled SQLite DB (deterministic)
uv run python -m nora.app "What was our best-selling product in Colombo last quarter?"
uv run python evals/run_evals.py --suite all
uv run langgraph dev                        # optional: serve the graph + view traces in Studio
```

The bundled database is committed, so the seed step is only needed if you want to rebuild it
(it reproduces byte-for-byte). Running the app and the evals needs a provider key; the tests do
not (see [Testing](#testing)).

### Web UI (Next.js + Aegra)

Beyond the CLI and LangGraph Studio, there's a browser chat UI. It talks to the `nora` graph
through **[Aegra](https://github.com/aegra/aegra)** — a self-hosted Agent Protocol backend
(FastAPI + Postgres) — using the official `@langchain/langgraph-sdk`:

```
Next.js (useStream) ──Agent Protocol──▶ Aegra ──▶ nora orchestrator graph
```

Aegra serves the graph (registered in `aegra.json` via the `make_graph` factory) and provides
the Postgres checkpointer + semantic store at runtime, so HITL interrupts persist and resume,
and the store propagates into the analytics/marketing subgraphs. The graph code is unchanged —
that's the point of the Agent Protocol.

```bash
# Backend (repo root) — needs Docker (Postgres) + OPENAI_API_KEY:
uv sync --extra aegra
uv run aegra dev                       # serves nora on http://localhost:2026
uv run python scripts/seed_store.py    # seed brand voice + metric definitions into the store

# Frontend:
cd frontend && cp .env.local.example .env.local && npm install && npm run dev   # http://localhost:3000
```

The UI streams Nora's answers, renders the marketing **approval card** (approve / edit / reject
the script), and shows the final **VideoBrief**. See [`frontend/`](frontend/) for details.

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
| **Routing** | `orchestrator.py` | Orchestrator + HITL (0:55–1:05) |
| **Human-in-the-loop (`interrupt`)** | `marketing` `human_review` node | Orchestrator + HITL |
| **Memory: checkpointer + semantic Store** | `memory.py`, read via `runtime.store` in both | Orchestrator + HITL |
| **Observability (structlog + LangSmith)** | `observability.py` | Observability + evals (1:05–1:25) |
| **Evaluation (deterministic + LLM-judge)** | `evals/` | Observability + evals |
| Ports & adapters, reliability | `services/`, `tenacity`, typed `SqlError` | Extensibility (1:25–1:30) |

## How the pieces work

**Analytics agent (`analytics/graph.py`).** The loop is hand-written so it's visible:
`START → llm → should_continue → (tools | END)`, with `tools → llm` looping back. A failed
`run_sql` raises `SqlError`; `ToolNode(handle_tool_errors=handle_sql_error)` turns it into a
ToolMessage (the DB error), so the model reads it, fixes the query, and retries. The error
handler is annotated `(error: SqlError)`, so only SQL errors are caught — real bugs still fail
loud. The production shortcut (`create_agent`) is shown in an appendix comment.

**Marketing workflow (`marketing/graph.py`).** A deterministic subgraph:
`fetch_product → load_brand → ideate∥ → choose_concept → write_script → human_review → storyboard
→ shot_prompt_worker∥ → critique → (assemble | revise)`. Concept ideation runs in parallel
within a node; per-shot prompts fan out with `Send` and gather via a reducer; `critique → revise`
loops until it passes or hits `marketing_max_revisions`. The single HITL gate sits before the
expensive creative steps — gate by risk.

**Memory (`memory.py`).** A checkpointer (short-term, makes interrupt/resume work) and a semantic
Store (long-term). Both are compiled into the graph and actually read in nodes via `runtime.store`:
analytics pulls metric **definitions**, marketing pulls **brand voice**.

**Observability (`observability.py`).** Structured `structlog` events with consistent keys
(`route.decided`, `sql.run`, `sql.error`, `hitl.raised`, `marketing.revision`, `eval.scored`),
never `print()`. LangSmith tracing turns on automatically when `LANGSMITH_TRACING=true`.

**Evaluation (`evals/`).** Two styles, on purpose. Analytics is graded against ground truth
*derived from the data itself* (run the item's `reference_sql`) plus a trajectory recovery metric.
Marketing is graded with deterministic guardrails (duration, shot counts, hook, CTA, product
grounding, banned claims) plus an LLM-as-judge rubric. The HITL gate is auto-approved in eval mode.

## Project layout

```
src/nora/
  config.py            settings (pydantic-settings); model strings; data_as_of
  observability.py     structlog setup + event helpers
  schemas.py           Pydantic LLM contracts + Context dataclass
  state.py             TypedDict graph states + reducers
  memory.py            build_store / build_checkpointer / seed_brand_knowledge
  orchestrator.py      the router graph (entry point) + make_graph for `langgraph dev`
  app.py               demo CLI (streams a turn, prompts on HITL)
  analytics/           tools.py · prompts.py · graph.py   (the AGENT)
  marketing/           prompts.py · nodes.py · graph.py   (the WORKFLOW)
  services/            interfaces.py (ports) · spice_db.py · renderer.py
  data/                seed.py + the committed curry_nomad.db
evals/                 datasets (.jsonl) · evaluators.py · run_evals.py
tests/                 offline tests (fakes drive every graph without an API key)
```

## Testing

```bash
uv run pytest        # offline: scripted fake models drive every graph (no API key needed)
uv run ruff check .  # lint
```

The whole suite runs without a provider key by injecting fake models — the SQL self-correction
loop, the marketing workflow, HITL pause/resume, routing, and the eval harness are all exercised
offline. A handful of `@pytest.mark.skipif` tests run live end-to-end when `OPENAI_API_KEY` is set.

## Production swaps (the "you'd change one line" coda)

- **Renderer:** `PlaceholderRenderer` (default, no external calls) ↔ `OpenRouterRenderer`
  (`services/renderer.py`, stubbed for M7) via `NORA_RENDERER`.
- **Checkpointer:** `InMemorySaver` → `SqliteSaver` / `PostgresSaver` (`langgraph.checkpoint.*`).
- **Store:** `InMemoryStore` → `PostgresStore` / `RedisStore`.

These are wiring changes only — no graph changes — which is the ports-&-adapters lesson.

## Specs

Built to the specs in [`specs/`](specs/) (read in order): API contracts, implementation spec,
data & evals, and milestones. Higher-level context is in
[`docs/CASE_STUDY_PLAN.md`](docs/CASE_STUDY_PLAN.md).

Stack: LangGraph 1.x · LangChain 1.x · Python 3.12 (uv) · pydantic / pydantic-settings ·
structlog · tenacity · SQLite · pytest · ruff. No secrets in code; `.env` only (the DB seed is
intentionally committed).
