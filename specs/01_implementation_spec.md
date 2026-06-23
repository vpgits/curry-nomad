# Implementation Spec — Curry Nomad agentic app

> The granular, build-ready spec. Contracts and wiring only (no implementation code). API specifics are validated in `00_api_contracts.md`. Data + evals in `02_data_and_evals.md`. Milestones + acceptance in `03_milestones.md`.

## 1. Principles (the things the demo teaches, encoded as rules)

1. **Provider-agnostic.** Every model is built via `init_chat_model(<config string>)`. No provider SDK imported directly. Switching providers is an env change.
2. **Agent where open-ended, workflow where predictable.** Analytics = hand-built agent loop (teaches the loop). Marketing = deterministic workflow subgraph (teaches chaining/evaluator-optimizer/parallel).
3. **Gate by risk.** Reads are never gated. The one HITL gate sits before the *expensive* creative-generation step.
4. **Memory is wired and used.** Checkpointer (short-term) + semantic Store (long-term), both compiled into the graph and actually read in nodes.
5. **Observe everything.** Structured logs + LangSmith traces. No `print()`.
6. **Deterministic & safe.** Bundled SQLite (no external data dep). Rendering is a placeholder adapter by default (no external calls, no spend).
7. **Ports & adapters.** External effects sit behind interfaces with swappable implementations.

## 2. Project structure

```
curry-nomad/
  pyproject.toml                # uv project; deps + extras
  langgraph.json                # registers graph(s) for `langgraph dev` (optional but nice for the demo)
  .env.example
  README.md
  src/nora/
    __init__.py
    config.py                   # pydantic-settings Settings
    observability.py            # structlog setup + event helpers; LangSmith via env
    schemas.py                  # Pydantic contracts (LLM I/O) + dataclass Context
    state.py                    # TypedDict graph states
    memory.py                   # build_store(), build_checkpointer(), namespaces, seed_brand_knowledge()
    prompts.py                  # all prompts in one place (versioned constants)
    orchestrator.py             # the router graph (entry point) wiring analytics + marketing
    analytics/
      __init__.py
      tools.py                  # @tool: list_tables, describe_table, run_sql
      graph.py                  # the agent loop subgraph
      prompts.py                # analytics system prompt builder
    marketing/
      __init__.py
      graph.py                  # the workflow subgraph
      nodes.py                  # node fns (ideate, script, review, storyboard, shot worker, critique, revise, assemble)
      prompts.py
    services/
      __init__.py
      interfaces.py             # Protocols: SpiceDB, Renderer
      spice_db.py               # SQLite-backed SpiceDB (deterministic, bundled)
      renderer.py               # PlaceholderRenderer (default) + OpenRouterRenderer (stub)
    data/
      seed.py                   # builds curry_nomad.db deterministically
      curry_nomad.db            # committed seed artifact
    app.py                      # demo CLI: one entrypoint to run a turn end-to-end (stream_events v3)
  evals/
    analytics_dataset.jsonl
    marketing_dataset.jsonl
    evaluators.py
    run_evals.py
  tests/
    test_tools.py
    test_spice_db.py
    test_analytics_graph.py
    test_marketing_graph.py
    test_router.py
```

## 3. `config.py` — settings contract

`pydantic-settings.BaseSettings`, env prefix `NORA_`, loads `.env`.

| Field | Type | Default | Notes |
|---|---|---|---|
| `model` | str | `"openai:gpt-4o"` | main reasoning model (`provider:model`) |
| `router_model` | str | `"openai:gpt-4o-mini"` | cheap classifier |
| `embedding_model` | str | `"openai:text-embedding-3-small"` | Store index embedder |
| `embedding_dims` | int | `1536` | must match the model |
| `db_path` | Path | `src/nora/data/curry_nomad.db` | bundled SQLite |
| `data_as_of` | date | `2026-06-30` | fixed "today" for deterministic time queries |
| `max_sql_rows` | int | `200` | LIMIT cap injected into run_sql |
| `sql_timeout_s` | float | `5.0` | statement timeout |
| `marketing_max_revisions` | int | `2` | evaluator-optimizer loop bound |
| `marketing_num_concepts` | int | `3` | parallel ideation count |
| `renderer` | Literal["placeholder","openrouter"] | `"placeholder"` | adapter selection |
| `openrouter_api_key` | str \| None | `None` | only used by openrouter renderer |
| `openrouter_base_url` | str | `https://openrouter.ai/api/v1` | OpenRouter API base |
| `openrouter_image_model` | str | `black-forest-labs/flux.2-flex` | image-gen model (OpenRouter id) |
| `openrouter_video_model` | str | `google/veo-3.1-lite` | video-gen model (OpenRouter id) |
| `render_aspect_ratio` / `render_resolution` | str | `9:16` / `720p` | reel format + resolution |
| `render_video_duration_s` | int | `6` | per-shot clip length |
| `render_generate_audio` | bool | `False` | audio adds cost/latency |
| `render_max_shots` | int | `4` | cap shots rendered (cost guard) |
| `media_dir` | Path | `…/data/runtime/media` | where stills are written (served by ops-api `/media`) |
| `media_public_base_url` | str \| None | `None` | public origin for image→video first-frame; unset → text→video |

LangSmith tracing is configured purely by standard env vars (`LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`) — not in Settings. Provider keys (`OPENAI_API_KEY` etc.) read from env by the integration packages. **No secret ever lives in code or in committed files.**

`get_settings()` returns a cached singleton.

## 4. `observability.py`

- `setup_logging(level)` — configures `structlog` to emit JSON (or pretty in dev), bound with a `run_id`/`thread_id` processor.
- `get_logger(name) -> structlog.BoundLogger`.
- Helper events the code emits (consistent keys): `route.decided` (capability, reason), `sql.run` (query, rows, ms), `sql.error` (query, error) + `sql.repair`, `hitl.raised`/`hitl.resumed`, `marketing.revision` (iteration, verdict), `eval.scored`.
- LangSmith tracing is automatic when env is set — document that a trace shows the agent loop and the workflow supersteps; nothing to wire in code.

## 5. `schemas.py` — typed contracts (Pydantic + dataclass)

```python
# Router  (post-M8: "routing" added for delivery-route requests — see §15)
class RouteDecision(BaseModel):
    capability: Literal["analytics", "marketing", "routing", "clarify"]
    reason: str
    product_hint: str | None = None     # product name/id if a marketing request references one

# Marketing creative contracts
class ConceptIdea(BaseModel):
    angle: str
    hook: str
    rationale: str

class ScriptBeat(BaseModel):
    t_start_s: float
    t_end_s: float
    voiceover: str
    on_screen_text: str | None = None

class Shot(BaseModel):
    index: int
    scene_description: str
    duration_s: float

class ShotPrompt(BaseModel):
    index: int
    t2v_prompt: str        # the text-to-video generation prompt for this shot

class Critique(BaseModel):
    passed: bool
    issues: list[str]
    suggestions: list[str]

class VideoBrief(BaseModel):
    product_name: str
    concept: str
    hook: str
    target_duration_s: float
    platform: str = "instagram_reel"
    script_beats: list[ScriptBeat]
    shots: list[Shot]
    shot_prompts: list[ShotPrompt]
    cta: str
    music_mood: str
    hashtags: list[str]
    product_facts_used: list[str]   # for the grounding eval

# Runtime context (per-run; injected via context_schema)
@dataclass
class Context:
    user_id: str = "arun"           # single demo user; namespaces the store
    model: str | None = None        # optional per-run model override
```

## 6. `services/` — ports & adapters

### `interfaces.py` (Protocols)
```python
class SpiceDB(Protocol):
    def list_tables(self) -> list[str]: ...
    def describe_table(self, table: str) -> dict: ...        # {columns:[{name,type}], sample_rows:[...]}
    def run_sql(self, query: str) -> dict: ...               # {columns, rows, row_count}; raises SqlError on bad SQL

class Renderer(Protocol):
    def render(self, brief: VideoBrief) -> dict: ...         # {status, asset_ref|None, detail}
```

### `spice_db.py` — `SqliteSpiceDB(SpiceDB)`
- Opens the bundled SQLite read-only (`file:...?mode=ro`).
- `run_sql` guards (this is where the "safe tool" lesson lives):
  - reject anything that isn't a single `SELECT`/`WITH … SELECT` (parse first keyword; block `;`-chained statements, `PRAGMA`, DDL/DML);
  - inject/enforce `LIMIT <max_sql_rows>` if absent;
  - apply `sql_timeout_s` via `sqlite3` progress handler or `set_progress_handler`;
  - raise a typed `SqlError(message)` with the DB error text on failure (the tool surfaces this so the agent self-corrects).
- Deterministic: same DB file + same query → same rows.

### `renderer.py`
- `PlaceholderRenderer(Renderer)` — **default.** Returns a `RenderResult` stub (`status="placeholder"`, `mode="none"`, no shots); no external calls, no spend.
- `OpenRouterRenderer(Renderer)` — **implemented** (post-M7; see §18). Generates a hero image + a per-shot still (synchronously, OpenRouter `/images`) and submits one image→video job per shot (`/videos`), returning a `RenderResult` whose shots carry `image_url` + `video_job_id` for the UI to poll. Talks to OpenRouter through `services/openrouter.py` (an injectable client, so tests run offline). `get_renderer(settings) -> Renderer` selects by `settings.renderer`.

## 7. `memory.py`

- Namespaces: `BRAND = ("curry_nomad", "brand")`, `DEFINITIONS = ("curry_nomad", "definitions")`.
- `build_store(settings) -> InMemoryStore` with `index={"embed": init_embeddings(settings.embedding_model), "dims": settings.embedding_dims, "fields": ["text","$"]}`.
- `build_checkpointer() -> InMemorySaver`.
- `seed_brand_knowledge(store)` — idempotently `store.put` the brand voice (e.g. *"warm, a little cheeky, proudly Sri Lankan; celebrate origin and authenticity"*) and a couple of metric definitions (*"revenue = sum(order_items) − refunds"*, *"a week starts Monday"*). Called once at startup.
- Nodes read memory via `runtime.store.search(NAMESPACE, query=..., limit=3)` and inject results into the relevant prompt. (Per docs: access is `runtime.store`, not a bare `store` param.)

## 8. `state.py` — graph states (TypedDict only; required by create_agent and clean for StateGraph)

```python
class OrchestratorState(TypedDict):
    messages: Annotated[list, add_messages]
    route: NotRequired[RouteDecision]

class AnalyticsState(TypedDict):              # subgraph
    messages: Annotated[list, add_messages]

class MarketingState(TypedDict):              # subgraph
    request: str
    product_hint: str | None
    brand_voice: str
    concepts: Annotated[list[ConceptIdea], operator.add]   # parallel ideate (gather)
    chosen_concept: NotRequired[ConceptIdea]
    script_beats: NotRequired[list[ScriptBeat]]
    approved: NotRequired[bool]
    shots: NotRequired[list[Shot]]
    shot_prompts: Annotated[list[ShotPrompt], operator.add] # Send fan-in (gather)
    critique: NotRequired[Critique]
    revision_count: int
    brief: NotRequired[VideoBrief]
    render_result: NotRequired[dict]
```

## 9. Orchestrator graph (`orchestrator.py`) — the routing pattern

Nodes & flow:
```
START → route → (Command goto) → analytics | marketing | clarify → END
```
> **Post-M8/M9 (see §15–§17):** `route` also dispatches to a deterministic **`routing`** node (delivery routes via the ops API). `analytics` is wired as a **real subgraph node** so its tool steps + answer stream inline, then flows through an `analytics_dashboard` node that attaches a generative-UI card. Each capability pushes typed UI cards via `push_ui_message` (§16).
- **`route` node:** builds `init_chat_model(settings.router_model).with_structured_output(RouteDecision)`, classifies the latest user message, logs `route.decided`, returns `Command(goto=decision.capability, update={"route": decision})`. (Routing via `Command(goto=...)`, per docs.)
- **`analytics` node:** invokes the compiled analytics subgraph with the messages; appends its final AI message.
- **`marketing` node:** seeds `MarketingState` from the route (`request`, `product_hint`), invokes the marketing subgraph, appends a summary AI message + attaches the `VideoBrief` (as message content / structured field).
- **`clarify` node:** emits a single clarifying question, ends.
- Compile the top graph with `checkpointer=InMemorySaver()` and `store=build_store(...)` so HITL + memory work end-to-end.

> The two capabilities are compiled subgraphs invoked inside the orchestrator nodes. (Keeps each independently runnable/testable — milestones M1/M2 build them standalone before M4 wires the router.)

## 10. Analytics agent (`analytics/graph.py`) — the AGENT loop

Hand-built (teaches the loop explicitly). Production shortcut noted in §13.

**Tools (`analytics/tools.py`):** `list_tables`, `describe_table`, `run_sql` — thin `@tool` wrappers over the module-level `SqliteSpiceDB`. `run_sql` lets `SqlError` propagate so `ToolNode(handle_tool_errors=...)` converts it to a `ToolMessage` (self-correction).

**Nodes/edges:**
```
START → llm → should_continue → (tools | END)
tools → llm                                  # loop
```
- `llm` node: `model = init_chat_model(settings.model, temperature=0).bind_tools([list_tables, describe_table, run_sql])`. System prompt (built in `analytics/prompts.py`) includes: the table list, "inspect schema before querying", SQLite dialect, `data_as_of` as "today", and **metric definitions pulled from the Store** (`runtime.store.search(DEFINITIONS, query=user_msg)`). Returns the model message.
- `tools` node: `ToolNode([list_tables, describe_table, run_sql], handle_tool_errors=handle_sql_error)` where `handle_sql_error(e) -> str` returns the DB error text (logged as `sql.error`).
- `should_continue(state) -> Literal["tools", END]`: `"tools"` if `state["messages"][-1].tool_calls` else `END`.
- Compile with the shared checkpointer + store (or accept them from the orchestrator).

**Self-correction demo path:** an intentionally tricky question makes the model write SQL referencing a wrong column → `run_sql` raises → ToolNode returns the error → model reads it, fixes, retries. This is the headline "why agents" moment and is eval'd (recovery rate).

## 11. Marketing workflow (`marketing/graph.py`) — the WORKFLOW

Subgraph nodes (in `marketing/nodes.py`); each is a plain function, model built via `init_chat_model(settings.model)`, structured outputs via `.with_structured_output(...)`.

```
START → load_brand → ideate(∥) → choose_concept → write_script
      → human_review (interrupt)  ──reject──────────────→ cancel → END
                 │approve/edit
                 ▼
        storyboard → [fan-out Send] shot_prompt_worker(∥) → critique
        critique ──pass OR revisions≥max──→ assemble → render → END
                 └──fail & < max──→ revise → storyboard   (evaluator-optimizer loop)
```

Node contracts:
- **`load_brand`** — `runtime.store.search(BRAND, query="tone & style", limit=3)` → `brand_voice` in state.
- **`ideate`** — produce `marketing_num_concepts` `ConceptIdea`s **in parallel** (one model call per concept via `asyncio.gather`, or a single structured call returning a list). Demonstrates *parallel within a node*. Appends to `concepts`.
- **`choose_concept`** — pick the best concept (structured pick or first); set `chosen_concept`.
- **`write_script`** — produce `list[ScriptBeat]` (~30s, grounded in product facts from `SpiceDB.describe`/a product lookup + brand voice).
- **`human_review`** — `decision = interrupt({"question":"Approve this 30s script?","script_beats": ...})`; logs `hitl.raised`. Returns `Command(goto=..., update=...)`: approve → keep script; edit → replace `script_beats` from `decision["edited_script"]`; reject → `Command(goto="cancel")`. **interrupt called exactly once** (node re-runs on resume).
- **`storyboard`** — turn approved script into `list[Shot]`.
- **fan-out** — conditional edge `fan_out_shots(state) -> [Send("shot_prompt_worker", {"shot": s}) for s in state["shots"]]`. Demonstrates *map-reduce parallel* (the `Send` pattern).
- **`shot_prompt_worker`** — receives one `{"shot": Shot}`, returns `{"shot_prompts": [ShotPrompt(...)]}` (reducer gathers all).
- **`critique`** — evaluator: score the draft (script + shot prompts) against brand voice + platform rules (hook in first 3s, clear CTA, target duration, product facts used) → `Critique`. Logs `marketing.revision`.
- **revise edge** — `route_after_critique(state)`: `"assemble"` if `critique.passed` or `revision_count >= marketing_max_revisions`; else `"revise"`.
- **`revise`** — apply `critique.suggestions` to the script; `revision_count += 1`; loop back to `storyboard`.
- **`assemble`** — build the `VideoBrief` from state.
- **`render`** — `get_renderer(settings).render(brief)` → `render_result` (placeholder by default).
- **`cancel`** — emit "creative cancelled by user", END.

Compile with the shared checkpointer (HITL needs it) + store.

## 12. Reliability

- **SQL self-correction** via `ToolNode(handle_tool_errors=...)` (above).
- **Flaky model/render calls:** set per-node `retry_policy=RetryPolicy(...)` (`langgraph.types`) on model-bound nodes; `init_chat_model(..., max_retries=6)` already retries 429/5xx.
- **SQL guards** in `SqliteSpiceDB` (SELECT-only, LIMIT, timeout) — defense in depth + a teachable "gate the tool" point.
- **No bare excepts.** Typed `SqlError`; everything else logged with context and re-raised.

## 13. Entry points & running

- **`app.py`** — a small CLI: `python -m nora.app "What was our best-selling product in Colombo last quarter?"`. Builds the orchestrator, runs `graph.stream_events(..., version="v3")`, prints streamed messages, and on `stream.interrupts` prompts the operator in the terminal (approve/edit/reject) then resumes with `Command(resume=...)`. This is what the instructor drives live.
- **`langgraph.json` → `aegra.json` (post-launch).** The serving layer moved from `langgraph dev` to **Aegra** (a self-hosted, Postgres-backed Agent Protocol backend). `aegra.json` registers the orchestrator as `nora` (plus `nora_a2ui`, §17) and carries the same `store.index` block; Aegra provides a Postgres checkpointer + semantic Store at runtime. Unlike `langgraph dev`, Aegra enforces no blocking-call check, so the synchronous `.invoke()` subgraph calls need no flag. Run `aegra dev` / `aegra serve` (`uv sync --extra aegra`). The graph code is unchanged — the point of the Agent Protocol.
- **Production shortcut appendix:** a commented reference showing the analytics agent rebuilt in ~5 lines with `create_agent(model=..., tools=[...], system_prompt=..., checkpointer=..., response_format=...)` — to make the "you'd normally use the prebuilt; here's what it hides" point.

## 14. Open ⚠️ verify items (confirm at first touch)
- `store=` kwarg on `create_agent` (use `.compile(store=...)` on hand-built graphs regardless).
- `with_structured_output` exact return for `TypedDict` vs `BaseModel` (docs: BaseModel → instance).
- `handle_tool_errors` default behavior when unset.
- OpenRouter's current text-to-video API surface (for the real renderer).

---

# Post-M7 additions

> The original spec (§1–§14) describes the two-capability build. The sections below were added with the operations subsystem (M8) and the generative-UI layer (M9). They extend the same architecture — same principles, same ports-&-adapters discipline.

## 15. Operations subsystem (`operations/`) — the deterministic, non-agentic backend

The "limits of agentic development" made **structural**, not a lecture: a real operations backend the agent can only *call*, so it cannot oversell or invent a route. Layered, each layer with one job:

- **`schema.py`** — DDL for a **writable** SQLite DB (`ref_products`/`ref_customers` snapshots, `stock_levels`, an append-only `stock_ledger`, `ops_orders`/`ops_order_items`, `routes`/`deliveries`), kept **separate** from the read-only `curry_nomad.db` so the committed dataset stays pristine. Core invariants (`reserved <= on_hand`, both `>= 0`) are CHECK-enforced at the DB layer too.
- **`interfaces.py`** — `OperationsStore` Protocol (read-write data access + a `tx()` transaction seam; **zero** business rules). Mirrors `services/interfaces.py:SpiceDB` — a Postgres adapter is wiring-only.
- **`store.py`** — `SqliteOperationsStore(OperationsStore)`: fresh connection per call, `PRAGMA foreign_keys=ON`, `tx()` drives `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK`.
- **`models.py`** — frozen, JSON-native dataclasses (`StockRow`, `LedgerEntry`, `Order`, `RoutePlan`, `RouteStop`, …) that `asdict` straight to the REST layer.
- **`services.py`** — the **single source of truth for every business rule**. Every function takes an injected `OperationsStore` (testable, no globals); every mutation runs in one `tx()` (stock UPDATE + ledger INSERT commit together or not at all); every rejection raises **`OperationsError`** with a human-readable message (the deliberate analogue of `SqlError` — a narrow, intentional exception callers translate, while any other exception fails loud). Timestamps come from `settings.data_as_of`, never the wall clock.
- **`routing.py`** — a pure, deterministic delivery-route optimizer: **haversine** distance matrix → **nearest-neighbor** greedy tour → **2-opt** local search, reporting `naive_km` (input order, "no planning") as the baseline the demo contrasts against. No solver dep, no `random`, no wall-clock. This is the headline lesson: vehicle routing is NP-hard, so we don't ask the LLM to guess a tour — it calls *this*.
- **`geo.py`** — fixed `(lat, lng)` for the depot + delivery cities (a constant, so seed and services share coordinates).
- **`seed.py`** — `python -m nora.operations.seed` builds the writable DB deterministically (fixed RNG seed, no wall-clock; snapshots reference data + derives initial stock from real sales volume; plants below-reorder SKUs and a zig-zag delivery set).
- **`api.py`** — a **thin** FastAPI layer: each route parses, calls the matching `services.*`, returns JSON. No business logic. One handler turns `OperationsError` into a structured `409` (and 404 for missing ids). Served by `nora-ops-api` on :8000 — **no LLM, no API key**.

**The `routing` capability** (in `orchestrator.py`): a deterministic node (no LLM) that plans today's route by calling the ops API (`POST /routes/plan`) — the **same** endpoint the web app uses — so the writable DB stays single-owner (no dual-writer SQLite). The planner is injectable (`route_planner`) so offline tests supply a canned plan. It pushes a `route_map` card (§16); if the ops service is unreachable it replies in text, never crashes.

New `Settings` fields: `ops_db_path` (writable DB, package-relative), `ops_api_url` (default `http://localhost:8000`). New `operations` extra (`fastapi`, `uvicorn`, `httpx`) and scripts `nora-ops-seed` / `nora-ops-api`.

## 16. Generative UI — native `push_ui_message` (no CopilotKit)

Each capability attaches typed UI **cards** to its final message; the web client renders them via `LoadExternalComponent`. The chat is `useStream` → Aegra; gen-UI is push-based and native.

- **Channel:** `from langgraph.graph.ui import push_ui_message` → `push_ui_message("<name>", payload_dict, message=ai_message)`. The card is anchored to the message id; the client maps the name to a React component.
- **Cards:** `analytics_dashboard` (composed post-hoc by a `dashboard_model` from the agent's final answer + the SQL it ran); the marketing set `video_brief` / `marketing_storyboard` / `marketing_script_timeline` / `marketing_critique`; and `route_map` (rendered as a Leaflet map).
- **Schemas (`schemas.py`):** `AnalyticsDashboard` = `title` + `stats: list[DashboardStat]` + optional `table: DashboardTable` + optional `chart: DashboardChart` (the builder model **chooses** `kind` ∈ `bar|line|pie|none` to fit the data — the canonical "agent picks the visualization" move).
- **Best-effort, never load-bearing:** every card build is wrapped — a failure (or no provider key offline, or a non-dashboard-worthy answer) skips the card; the streamed text answer is never blocked.
- **Streaming discipline:** the internal `with_structured_output` calls that build cards (router, `dashboard_model`, every marketing node) use `disable_streaming=True`, so their forced-tool-call deltas don't surface as phantom partial messages on Aegra's `messages` stream. Only the analytics agent streams — its tokens *are* the user-facing answer.
- **Second HITL gate:** with gen-UI, marketing gains an interactive `choose_concept` gate (`auto_choose=False`) whose `interrupt` payload carries `kind: "concept_pick"` (vs the script gate's `kind: "script_review"`), so the UI tells them apart.

## 17. A2UI studio (`a2ui_studio.py`, graph `nora_a2ui`) — the dynamic-schema contrast

Where §16's dashboard has a **fixed** shape, this graph lets a model **author** the surface — the "LLM authors the UI" (dynamic-schema A2UI) pattern, the deliberate mirror of the repo's agent-vs-workflow split (there the *code* picks components; here the *model* composes them).

- **Flow:** `START → analytics (subgraph) → ui_author → END`. `ui_author` composes from the same final answer + SQL the dashboard uses, and pushes an `a2ui_surface` card on the same native channel.
- **Schema:** `A2uiSurface` = an ordered `list[A2uiBlock]`; each block's `type` ∈ `heading|text|metrics|chart|table` selects which optional fields apply. **Deliberately one flat model, not a discriminated union** — OpenAI strict structured-output rejects `anyOf`/`oneOf`, so a union would make the authoring call throw (the same constraint shapes `AnalyticsDashboard`). Worth a `⚠️` note for anyone extending the block catalog.
- **Wiring:** `make_a2ui_graph()` is registered in `aegra.json` as `nora_a2ui` (Postgres checkpointer + Store injected by the platform, exactly like `make_graph()`); the web `/studio` route renders it via its block catalog.

## 18. Marketing rendering — real media via OpenRouter (the M7 "real adapter", implemented)

The `Renderer` port's real adapter. Placeholder stays the default (`NORA_RENDERER=placeholder`, no key, no spend); `NORA_RENDERER=openrouter` swaps in `OpenRouterRenderer` — pure wiring, no graph change (the ports-&-adapters payoff M7 promised).

- **Two OpenRouter surfaces (`services/openrouter.py`):** images are **synchronous** (`POST /images` → base64 `data[].b64_json`); video is an **async job** (`POST /videos` → `{id, polling_url}`, poll `GET /videos/{id}` until `completed`, then `unsigned_urls` / `…/content`). The client is a thin httpx wrapper (not `init_chat_model` — this isn't a chat model) and is **injectable** so the renderer's tests run offline against a fake.
- **What `render(brief)` does:** generate a hero image + a still per shot (capped at `render_max_shots`), persist them under `media_dir`, then submit one image→video job per shot and return a `RenderResult` (`status`, `mode`, `hero_image_url`, `shots:[{index, image_url, video_job_id, …}]`). It only *submits* video — the slow polling is the UI's job (the decision: don't block the chat turn for minutes).
- **Serving + the public-URL constraint:** stills are served by the **ops-api at `/media`** (keyless `StaticFiles`, on a dir/volume shared with the renderer). OpenRouter fetches the image→video first frame from a **public** URL, so image→video is used only when `media_public_base_url` is set; otherwise the renderer falls back to **text→video** (recorded in `RenderResult.mode`). Video status + content are proxied by the web's `app/api/render/video/[jobId]` route handlers (the OpenRouter key stays server-side); the `marketing_render` card (§16) polls them and swaps each still for a `<video>` when the job completes.
