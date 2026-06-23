# API Contracts — LangGraph / LangChain 1.x (doc-validated)

> Sourced from the live LangChain docs (docs.langchain.com, OSS Python) on the date of writing. These are the exact imports/signatures the implementation must use. Items marked **⚠️ verify** were not fully nailed in the docs and should be confirmed when first touched in code.

## Models (provider-agnostic — the project requirement)

```python
from langchain.chat_models import init_chat_model

# "provider:model" string → provider auto-resolved and integration package loaded
model = init_chat_model("openai:gpt-4o", temperature=0)
# one-line provider switch:
model = init_chat_model("anthropic:claude-sonnet-4-6", temperature=0)
# kwargs forwarded to the underlying chat model: temperature, max_tokens, timeout, max_retries (default 6)
```
- Provider can also be given via `model_provider=` (e.g. Bedrock). Prefix may be omitted when unambiguous.
- **Decision:** every model in the app is built through `init_chat_model` from a config string. No provider SDK is imported directly.

## Embeddings (for the semantic Store)

```python
from langchain.embeddings import init_embeddings
embeddings = init_embeddings("openai:text-embedding-3-small")  # 1536 dims
```

## Tools

```python
from langchain.tools import tool

@tool
def run_sql(query: str) -> str:
    """Run a read-only SQL query against the Curry Nomad database. SELECT only."""
    ...
```
- Description comes from the docstring; type hints define the schema.

## Structured output (router classifier, VideoBrief, EmailDraft-style outputs)

Two supported paths:
```python
# A) on a raw model — used for the router/classifier
structured = model.with_structured_output(RouteDecision)   # returns a RouteDecision instance

# B) on create_agent — returns the object under result["structured_response"]
agent = create_agent(model=..., tools=[...], response_format=VideoBrief)
result = agent.invoke({"messages": [...]})
brief = result["structured_response"]
```
`with_structured_output` exact return shape **⚠️ verify** (object vs dict) on first use; docs show a Pydantic instance.

## Prebuilt agent (the production shortcut)

```python
from langchain.agents import create_agent

agent = create_agent(
    model="openai:gpt-4o",            # string or initialized model
    tools=[...],
    system_prompt="...",              # NOTE: renamed from `prompt`
    response_format=SomeModel,        # → result["structured_response"]
    checkpointer=InMemorySaver(),
    context_schema=Context,           # dataclass, per-run context
    middleware=[...],                 # tool-error handling, dynamic prompt/model
)
```
- `store=` on create_agent is **⚠️ verify** (documented at `.compile(store=...)` level; create_agent likely accepts it).
- `create_agent` supports **TypedDict state only** (no Pydantic state).
- Tool-error handling is via middleware, not ToolNode (see below).

## Hand-built graph (the teaching centerpiece)

```python
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt, Command, Send
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.runtime import Runtime
from typing import Annotated, Literal
from typing_extensions import TypedDict
import operator
```

### State + reducers
```python
class State(TypedDict):
    messages: Annotated[list, add_messages]      # message-aware reducer
    shot_prompts: Annotated[list, operator.add]  # append/accumulate for fan-in
```

### Build / wire / compile
```python
builder = StateGraph(State, context_schema=Context)
builder.add_node("llm", llm_node)
builder.add_node("tools", ToolNode([run_sql], handle_tool_errors=handle_err))
builder.add_edge(START, "llm")
builder.add_conditional_edges("llm", should_continue, ["tools", END])
builder.add_edge("tools", "llm")                 # loop back
graph = builder.compile(checkpointer=InMemorySaver(), store=store)
```

### The agent loop (no `tools_condition` — hand-write the router)
```python
def should_continue(state) -> Literal["tools", END]:
    last = state["messages"][-1]
    return "tools" if last.tool_calls else END
```

### ToolNode error handling → enables SQL self-correction
```python
ToolNode([run_sql], handle_tool_errors=handle_err)
# handle_err(error: Exception) -> str   # returned string becomes the ToolMessage content
```
A raised tool exception is turned into a `ToolMessage` (the DB error text) fed back to the model, so it can repair the query and retry. (For `create_agent`, use `@wrap_tool_call` middleware instead.)

### Human-in-the-loop (interrupt)
```python
def human_review(state) -> Command[Literal["proceed", "cancel"]]:
    decision = interrupt({"question": "Approve this script?", "script": state["script"]})
    return Command(goto="proceed" if decision.get("approved") else "cancel")
```
- Resume: re-invoke with `Command(resume={...})`, **same `thread_id`**.
- Caller sees the payload at `result["__interrupt__"]` (invoke) or `stream.interrupts` (stream_events v3).
- **Requires** a checkpointer + `thread_id`. Node re-runs from the top on resume → call `interrupt()` exactly once per node; never loop `interrupt()` inside a node.

### Short-term memory (checkpointer)
```python
graph = builder.compile(checkpointer=InMemorySaver())
config = {"configurable": {"thread_id": "demo-1"}}   # thread_id REQUIRED
```
Production swap: `SqliteSaver` (`langgraph.checkpoint.sqlite`) / `PostgresSaver` (`langgraph.checkpoint.postgres`).

### Long-term memory (Store + semantic search)
```python
store = InMemoryStore(index={
    "embed": init_embeddings("openai:text-embedding-3-small"),
    "dims": 1536,
    "fields": ["text", "$"],     # which fields to embed; "$" = whole value
})
store.put(("curry_nomad", "brand"), "voice", {"text": "warm, a little cheeky, proudly Sri Lankan"})
results = store.search(("curry_nomad", "definitions"), query="how is revenue defined", limit=3)
# access from a node via the injected runtime:
def node(state, runtime: Runtime[Context]):
    items = runtime.store.search(("curry_nomad", "brand"), query="tone", limit=3)
```
- Namespace is a **tuple of strings**. `compile(store=store)`. Cross-thread (persists across `thread_id`s).
- Production swap: `PostgresStore` / `RedisStore`.

### Parallel fan-out (Send / map-reduce) — for per-shot video prompts
```python
def fan_out_shots(state):
    return [Send("shot_prompt_worker", {"shot": s}) for s in state["shots"]]

builder.add_conditional_edges("storyboard", fan_out_shots, ["shot_prompt_worker"])
builder.add_edge("shot_prompt_worker", "assemble")   # fan-in
# worker appends to state["shot_prompts"] (operator.add reducer)
```
- A superstep is transactional; set per-node `retry_policy` (`langgraph.types.RetryPolicy`) for flaky calls; `max_concurrency` via config.

### Streaming (for the demo CLI + clean HITL)
```python
# typed projections (recommended; needed for clean interrupt handling)
stream = graph.stream_events(inputs, config=config, version="v3")
stream.messages      # LLM token chunks
stream.interrupts    # pending HITL payloads
stream.output        # final state (drive stream to completion)
# or stream modes:
for part in graph.stream(inputs, config, stream_mode=["updates", "messages"]):
    ...
```

### Generative UI (native push) — `push_ui_message` → `LoadExternalComponent` (post-M9)
```python
from langgraph.graph.ui import push_ui_message

def analytics_dashboard(state) -> dict:
    final = state["messages"][-1]                      # the AI message the card anchors to
    dashboard = build_dashboard(...)                   # a Pydantic model → .model_dump()
    push_ui_message("analytics_dashboard", dashboard.model_dump(), message=final)
    return {"messages": [final]}                        # same id → add_messages merges in place (no dup)
```
- A node emits a typed UI **card** on the graph's UI channel, anchored to a message id. The client maps the card name → a React component and renders it with `@langchain/langgraph-sdk/react-ui`'s `LoadExternalComponent`. No CopilotKit.
- The web client must opt into subgraph streaming (`useStream({ streamSubgraphs: true, ... })`) so a subgraph node's messages + pushed cards surface in the parent thread.
- **Keep card builds best-effort** — wrap in try/except; a failure must skip the card, never block the streamed text answer.
- **`disable_streaming=True`** on any `with_structured_output` model whose result is consumed into state (router, dashboard, marketing) — otherwise its forced-tool-call deltas appear as phantom partial messages on the `messages` stream.

### Serving layer — Aegra (replaces `langgraph dev`, post-launch)
```jsonc
// aegra.json (was langgraph.json)
{
  "dependencies": ["./apps/nora/src"],
  "graphs": { "nora": "...orchestrator.py:make_graph", "nora_a2ui": "...a2ui_studio.py:make_a2ui_graph" },
  "store": { "index": { "embed": "openai:text-embedding-3-small", "dims": 1536, "fields": ["text", "$"] } }
}
```
- **Aegra** is a self-hosted, Postgres-backed Agent Protocol backend. `aegra dev` / `aegra serve` (install via `uv sync --extra aegra`). It injects a Postgres checkpointer + the semantic Store at runtime — so `make_graph()`/`make_a2ui_graph()` compile **without** their own.
- Unlike `langgraph dev`, Aegra enforces **no** blocking-call check — synchronous `.invoke()` subgraph calls and synchronous SQLite need no flag. Threads/Store persist across restarts (Postgres).
- The web client talks to it over the Agent Protocol via the official `@langchain/langgraph-sdk` `useStream` — graph code unchanged.

### OpenRouter media generation — images (sync) + video (async job) (post-M7 renderer)
```python
# Images: synchronous. POST /api/v1/images → base64 inline.
#   body: {model, prompt, aspect_ratio, n}
#   resp: {"data": [{"b64_json": "<...>"}], "usage": {"cost": 0.04}}
#
# Video: asynchronous job. POST /api/v1/videos → poll → download.
#   body: {model, prompt, duration, resolution, aspect_ratio, generate_audio,
#          frame_images?: [{"type":"image_url","image_url":{"url": <PUBLIC https url>},"frame_type":"first_frame"}]}
#   submit resp: {"id", "status", "polling_url"}            # 202
#   poll:  GET /api/v1/videos/{id} → status ∈ pending|in_progress|completed|failed|cancelled|expired
#   done:  {"status":"completed", "unsigned_urls": ["https://openrouter.ai/api/v1/videos/{id}/content?index=0"]}
```
- Auth: `Authorization: Bearer {OPENROUTER_API_KEY}`. Base: `https://openrouter.ai/api/v1`. These are **not** `init_chat_model` calls — a plain httpx client (`services/openrouter.py`).
- **`frame_images` present → image→video** (first-frame conditioned); absent → text→video. The first-frame `url` must be a **public, directly-downloadable** HTTPS URL (no base64/`localhost`) — OpenRouter's servers fetch it.
- Models are OpenRouter ids (`black-forest-labs/flux.2-flex`, `google/veo-3.1-lite`, …), not provider:model config strings.

## Reference doc pages to keep open while building
- `/oss/python/langgraph/sql-agent` — Build a custom SQL agent (anchors the analytics agent)
- `/oss/python/langgraph/interrupts` — HITL
- `/oss/python/langgraph/stores` + `/oss/python/langgraph/add-memory` — Store + semantic search
- `/oss/python/langgraph/use-graph-api` — Send / parallel / reducers
- `/oss/python/langchain/agents` + `/oss/python/migrate/langchain-v1` — create_agent + v1 changes
- `/oss/python/langchain/multi-agent/router` — routing pattern
- `/oss/python/langgraph/streaming` — streaming
