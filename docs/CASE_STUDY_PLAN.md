# Curry Nomad — Agentic Workflows Case Study
### Comprehensive build & teaching plan

A clean, runnable LangGraph application built **as a teaching artifact** — the reference codebase for a ~1.5-hour hands-on session showing engineers how to build agentic systems properly: orchestration, the agent loop, deterministic workflows, tools, human-in-the-loop, memory, observability, and evaluation.

> Supersedes the earlier `NORA_RESEARCH_BRIEF.md` and `NORA_ARCHITECTURE_DECISIONS.md` (those described a SaaS product, which is no longer the goal). Those can be deleted.

---

## 1. Purpose & framing

- **What it is:** a single, self-contained codebase that an instructor walks through live. Every concept is shown in *working code*, not slides.
- **Audience:** engineers comfortable with Python and LLM APIs, new to building agentic workflows.
- **The teaching thesis:** *the most important skill is knowing when to use an agent vs. a workflow, and how to make either production-grade* (evals, observability, HITL, memory). This app shows **both paradigms in one place**, under one orchestrator.
- **The pedagogical hook:** the old `api/` in this repo is a real "naive" agentic app full of the exact mistakes interns make (frozen clock, dead memory store, `print()` logging, ungated writes, no evals). The rewrite is the "after." Each best practice is motivated by a real bug.

**Goals**
- Demonstrate the full pattern catalog (routing, agent loop, chaining, evaluator-optimizer, parallelization).
- Make **evaluation** and **observability** first-class and *runnable live*.
- Run on any laptop with only an LLM API key — deterministic, safe, zero third-party setup.

**Non-goals**
- Not a product. No multi-tenancy, no auth, no real social/email APIs, no SaaS concerns.
- Not feature-complete. One excellent example of each pattern, not ten half-built ones.

---

## 2. The application

**Nora** is the operations assistant for **Curry Nomad**, a (fictional) Sri Lankan spice business. A top-level **orchestrator** routes each request to one of two capabilities:

1. **Analytics — the AGENT.** Answers questions about the business by querying a bundled SQLite database. Open-ended: the model decides the path, writes SQL, runs it, and *self-corrects when a query fails*.
2. **Marketing Studio — the WORKFLOW.** Generates a structured **video-ad creative package** for a product via a predictable multi-step pipeline with a human-review checkpoint.

**The canonical demo flow** (one coherent story):
> "What's our best-selling product in Colombo this quarter?" → *analytics agent runs SQL, self-corrects an error, answers* → "Great, make a 30-second video ad for it." → *marketing workflow pulls that product's data, drafts a script, pauses for human review, then produces the full creative brief.*

Same orchestrator, both paradigms, grounded in the same data.

---

## 3. Teaching objectives → where each lives

| Concept / pattern | Where it's demonstrated |
|---|---|
| **Routing** | orchestrator deciding analytics vs. marketing |
| **Agent loop + reflection** | analytics: SQL → error → repair → retry |
| **Prompt chaining** | marketing: gather → ideate → script → storyboard |
| **Evaluator-optimizer** | marketing: critique vs. brand voice → revise until it passes |
| **Parallelization** | marketing: concept options & per-shot prompts generated concurrently |
| **Tool design & gating by risk** | read-only analytics tools (no gate) vs. HITL on the costly workflow step |
| **Human-in-the-loop** | marketing: `interrupt()` review of the script mid-pipeline |
| **Memory (short + long term)** | checkpointer (thread/resume) + semantic Store (brand voice, metric definitions) used by *both* capabilities |
| **Observability** | structured logs + LangSmith traces across the agent loop *and* workflow steps |
| **Evaluation (two kinds)** | analytics = deterministic ground truth; marketing = LLM-judge + guardrails |
| **Reliability** | retries/backoff, SQL guards, typed errors |
| **Ports & adapters / testability** | services behind interfaces; fakes by default, real adapters optional |

---

## 4. Architecture

```
                       ┌──────────────────────────────┐
        request   →    │   ORCHESTRATOR (router graph) │   routing
                       └─────────┬───────────┬─────────┘
                                 │           │
                 ┌───────────────┘           └────────────────┐
                 ▼                                              ▼
   ┌──────────────────────────┐               ┌──────────────────────────────────┐
   │ ANALYTICS  (agent graph)  │              │ MARKETING STUDIO (workflow graph)  │
   │  list_tables/describe/    │              │  fetch → ideate∥ → script →        │
   │  run_sql · self-correct   │              │  ⏸review → storyboard →            │
   │  loop                     │              │  shot_prompts∥ → critique→revise → │
   │                           │              │  assemble brief → [render adapter] │
   └────────────┬─────────────┘              └─────────────────┬──────────────────┘
                └──────────────────┬───────────────────────────┘
                                   ▼
   shared layers:  memory (checkpointer + semantic Store)
                   approvals (one HITL mechanism)
                   observability (structlog + LangSmith)
                   services (ports → fakes default / real optional)
                   evals (deterministic + LLM-judge)
```

**Module-by-module:**

| Module | Responsibility |
|---|---|
| `config` | settings via `pydantic-settings`; model/provider configurable; no secrets in code |
| `observability` | `structlog` setup; LangSmith tracing toggle; event-logging helpers |
| `schemas` | Pydantic contracts for LLM I/O (structured outputs) |
| `services/` | **ports** (`Protocol`s) + `fakes` (default) + optional real adapters |
| `data/` | the Sri Lankan SQLite seed + a `seed.py` to build it |
| `analytics/` | the agent: tools (`list_tables`, `describe_table`, `run_sql`) + graph |
| `marketing/` | the workflow: chain + evaluator-optimizer + variants + `VideoBrief` |
| `memory` | checkpointer (short-term) + semantic Store (long-term) wiring |
| `approvals` | the single HITL `interrupt()` helper |
| `orchestrator` | the router graph tying both capabilities together |
| `prompts/` | clean, versioned prompts per capability |
| `evals/` | dataset + evaluators (deterministic + LLM-judge) + runner |
| `tests/` | unit tests for tools/services + graph smoke tests |

---

## 5. Capability A — Analytics (the AGENT)

**Pattern:** augmented LLM in a tool loop with self-correction. This is the safe, reproducible answer to *"why agents, not a fixed pipeline?"*

**Graph:**
```
agent (LLM + tools) ──tool_calls?──> tools (ToolNode) ──> agent ──no tool_calls──> END
```

**Tools (read-only by design — gate by risk, and there's no risk here):**
- `list_tables() -> list[str]`
- `describe_table(table: str) -> {columns, types, sample_rows}`
- `run_sql(query: str) -> {rows, row_count} | {error}` — **SELECT-only** (reject DDL/DML), enforced `LIMIT`, statement timeout. On failure it returns the DB error *as a tool result* so the model can read it and repair.

**The self-correction loop is the lesson:** a malformed query → `run_sql` returns the error → the model reads it, fixes the SQL, retries. We demonstrate it deliberately (and eval it — see §11).

**Prompt:** schema-aware system prompt that injects the table list, tells the model to inspect before querying, to use SQLite dialect, and to apply any user metric definitions from memory (e.g. "revenue = net of refunds").

---

## 6. Capability B — Marketing Studio (the WORKFLOW)

**Pattern:** a deterministic, multi-step pipeline (a LangGraph subgraph) that produces a structured **video-ad creative package**, grounded in the product's real data.

**Steps:**
```
fetch_product        pull facts from SQLite (name, origin, price, category)
ideate_concepts ∥    generate 2–3 concept options in parallel
write_script         pick/compose a ~30s script (timed beats)
⏸ human_review       interrupt() — approve or edit the script        ← HITL
storyboard           break the script into shots
shot_prompts ∥       per-shot text-to-video prompts (parallel)
critique             evaluator: brand voice + platform rules
                     (hook in first 3s, clear CTA, duration target)
revise               optimizer: fix issues; loop ≤ N times
assemble             produce the VideoBrief (structured output)
[render]             OPTIONAL adapter — fake by default
```

**Output schema (`VideoBrief`):**
```
concept, hook, target_duration_s, platform,
script_beats: [{t_start, t_end, voiceover, on_screen_text}],
shots: [{scene_description, t2v_prompt, duration_s}],
music_mood, cta, hashtags, product_facts_used
```

**Why HITL here (not on publishing — which we dropped):** the review is a **mid-pipeline checkpoint** — approve/edit the script *before* compute is spent on storyboard + per-shot prompts (+ optional render). This teaches HITL as a pipeline gate, not just a final "are you sure?".

**Rendering is an optional adapter** (parallel to the optional real Google adapter): fake by default (returns the prompts / a stub reference); a real text-to-video model is a config swap. The *workflow* is the teaching target, not the MP4.

---

## 7. The orchestrator (routing)

A small router graph classifies the request and dispatches:
- data/metrics question → **analytics agent**
- "make/generate an ad/video for …" → **marketing workflow** (resolving the product, possibly via a quick analytics lookup first)
- ambiguous → ask a clarifying question

Routing is done with a structured-output classifier (cheap model tier) — a clean example of the **routing** pattern and of using a small model for a small job.

---

## 8. Cross-cutting: memory

- **Short-term (checkpointer):** per-thread state + the mechanism that makes `interrupt()`/resume work. Use `InMemorySaver` for the demo (note: swap to `SqliteSaver`/`PostgresSaver` for persistence — a one-liner, called out as the extension).
- **Long-term (semantic Store):** business knowledge that shapes behavior across both capabilities:
  - `("curry_nomad", "brand")` — brand voice/guidelines (used by marketing).
  - `("curry_nomad", "definitions")` — metric definitions like "revenue = net of refunds", "week starts Monday" (used by analytics).
- Retrieved by semantic search on each run and injected into the relevant prompt. **This is wired in and actually used** — the contrast with the old code (where the store was built but never compiled into the graph) is a teaching beat.

---

## 9. Cross-cutting: observability

- **Structured logging** (`structlog`, JSON): every meaningful event — routing decision, each tool call with latency + row count, SQL error + repair, `interrupt` raised/resumed, eval scores — tagged with a correlation id (thread/run).
- **Tracing:** LangSmith via env (`LANGSMITH_TRACING=true`), automatic with LangChain/LangGraph. The live demo opens a trace to *show* the agent loop and workflow steps, token usage, and latency.
- **The lesson:** replace `print()` with structured events; a trace is your primary debugging tool for agents.

---

## 10. Cross-cutting: reliability, config, services

- **Reliability:** `tenacity` retries with backoff on model + DB calls; `run_sql` guards (SELECT-only, `LIMIT`, timeout); typed exceptions; no bare `except`.
- **Config:** `pydantic-settings`, env-driven. Key settings: `MODEL` (e.g. `openai:gpt-4o`, switchable to `anthropic:claude-opus-4-8`), `ROUTER_MODEL` (cheap tier), `EMBEDDING_MODEL`, `USE_FAKE_SERVICES=true`, `DB_PATH`, eval params. Secrets only via env, never committed.
- **Services / ports & adapters:** `CalendarService`-style interfaces — here `SpiceDB` (analytics data), `Publisher`/`Renderer` (marketing). **Fakes are the default**, so the app runs deterministically offline; real adapters (e.g. a text-to-video model) are optional swaps. This is the testability lesson.
- **Model layer:** provider-agnostic via `init_chat_model`. Tiering: a capable model for the agent/workflow reasoning, a cheap model for routing/classification. (Defaults match the existing OpenAI setup; Anthropic is a one-line switch.)

---

## 11. Cross-cutting: evaluation (the headline)

Two eval styles, taught in contrast — most demos can only show one.

**Analytics — deterministic / ground truth**
- Dataset: `[{question, ground_truth_value | ground_truth_sql}]`.
- Evaluators: numeric/exact-match against the value computed directly from the DB; SQL validity; **error-recovery** (inject a schema typo into a question and check the agent recovers).
- Metrics: answer accuracy, recovery rate, avg tool calls per question.

**Marketing — LLM-as-judge + guardrails**
- Dataset: `[{product, brief_request}]`.
- Deterministic guardrails: duration in target range, scene count in range, hook present, CTA present, **uses correct product facts from the DB**, no banned claims.
- LLM-judge: brand-voice adherence, hook quality, coherence — scored against a rubric (1–5).
- Metrics: guardrail pass-rate, mean judge score.

**Runner:** a local runner that works offline against fakes (so it runs in the demo with no account) + an optional LangSmith `evaluate` integration for the dashboard view. Run live during the session.

---

## 12. The dataset (synthetic, Sri Lankan, LKR)

Built by `data/seed.py` into a committed SQLite file.

| Table | Columns (key ones) |
|---|---|
| `products` | product_id, name, category, origin, grams, unit_price_lkr, sku, active |
| `customers` | customer_id, name, city, segment (`local`/`export`), created_at |
| `orders` | order_id, customer_id, order_date, status, channel |
| `order_items` | order_item_id, order_id, product_id, quantity, unit_price_lkr |
| `refunds` | refund_id, order_id, amount_lkr, reason, refund_date |

**Flavor:** products = Ceylon cinnamon, black pepper, cardamom, cloves, turmeric, chili powder, curry-powder blends, goraka, pandan/rampe, Maldive fish — with origins (Matale, Kandy, …). Customers across Colombo, Kandy, Galle, Jaffna, Negombo, Matara; `local` and `export` segments. ~12 months of orders so time-based questions work ("last quarter", "month over month"). Enough volume for meaningful aggregates and refund-rate questions.

Grounds both capabilities: analytics queries it directly; marketing pulls real product facts into the video brief (and the eval checks they're used correctly).

---

## 13. Tech stack

- **LangGraph 1.x** (graphs, `ToolNode`, `interrupt`, checkpointer, Store) + **LangChain 1.x** (`init_chat_model`, tools, structured output).
- **Python 3.12**, **uv** for env/deps.
- **pydantic / pydantic-settings** (contracts + config), **structlog** (logs), **tenacity** (retries), **SQLite** (bundled data).
- **LangSmith** (tracing + optional eval dashboard), **pytest** (tests), **ruff** (lint).
- Provider-agnostic model layer; defaults match existing OpenAI env, one-line Anthropic switch.

---

## 14. Project structure

```
curry-nomad/                 (or reuse repo root for the new project)
  pyproject.toml
  README.md                  # the teaching map + how to run + run-of-show
  .env.example
  src/nora/
    config.py
    observability.py
    schemas.py
    memory.py
    approvals.py
    orchestrator.py          # the router graph
    analytics/
      tools.py
      graph.py
      prompts.py
    marketing/
      graph.py               # the workflow subgraph
      schema.py              # VideoBrief
      prompts.py
    services/
      interfaces.py          # ports (Protocols)
      fakes.py               # default deterministic impls
      renderer.py            # optional real text-to-video adapter (stub by default)
    data/
      seed.py                # builds the Sri Lankan SQLite DB
      curry_nomad.db         # committed seed
  evals/
    analytics_dataset.jsonl
    marketing_dataset.jsonl
    evaluators.py
    run_evals.py
  tests/
    test_tools.py
    test_analytics_graph.py
    test_marketing_graph.py
```

---

## 15. Build milestones (each leaves the repo runnable)

| # | Milestone | Delivers |
|---|---|---|
| **M0** | Scaffold | project, config, observability, services + fakes, **the SQLite seed** |
| **M1** | Analytics agent | read tools + the agent loop + self-correction; runnable Q&A on the DB |
| **M2** | Marketing workflow | chain + parallel concepts/shot-prompts + evaluator-optimizer + `VideoBrief` |
| **M3** | HITL + memory | mid-workflow review (`interrupt`), checkpointer, semantic Store wired into both |
| **M4** | Orchestrator | router tying analytics + marketing into one entrypoint (the demo flow works) |
| **M5** | Evals | deterministic analytics evals + LLM-judge marketing evals + local runner |
| **M6** | Tests + docs + polish | pytest suite, README/teaching map, prompt cleanup, lint clean |
| **M7** *(opt.)* | Real adapters | swap a real text-to-video renderer / real DB — the "production I/O" coda |

---

## 16. The 1.5-hour run-of-show

| Time | Segment | Code shown / done live |
|---|---|---|
| 0:00–0:12 | Framing: workflow vs. agent | both paradigms live in this one app; when to use which |
| 0:12–0:35 | Analytics **agent** | the tool loop, self-correction on a bad query — *why agents* |
| 0:35–0:55 | Marketing **workflow** | chaining, parallel concepts/shots, evaluator-optimizer |
| 0:55–1:05 | Orchestrator + HITL + memory | routing, the script-review `interrupt`, brand voice shaping both |
| 1:05–1:25 | Observability + **evals** (run live) | open a trace; run both eval suites and read the metrics |
| 1:25–1:30 | Extensibility + before/after + Q&A | how to add a capability; quick diff vs. the old `api/` |

---

## 17. Extensibility (so "we can have it all" is a recipe, not a promise)

Adding a capability is a fixed five-step recipe — demonstrate it, don't pre-build it:
1. Define a **service interface** + a **fake** (and optionally a real adapter).
2. Add **tools** (for an agent) or a **subgraph** (for a workflow).
3. Register a **route** in the orchestrator.
4. Add **prompts** and any **memory** namespaces.
5. Add **evals** (deterministic and/or LLM-judge).

This is the takeaway for engineers: the architecture is the product; capabilities are pluggable.

---

## 18. Before / after — the anti-pattern gallery (teaching gold)

Each lesson is motivated by a real flaw in the old `api/`:

| Old `api/` flaw (real) | Rewrite teaches |
|---|---|
| `print()` everywhere | structured logging + tracing |
| No evals at all | the dual eval harness, run live |
| Semantic store built but never compiled into the graph; two embedding systems that never connect | memory actually wired (checkpointer + Store) |
| Decorative approval cards with dead buttons next to the real `interrupt()` | one clean HITL path |
| Workspace writes ungated; calendar/email gated inconsistently | gate by risk, uniformly |
| System prompt's "now" frozen at import time | freshness / config discipline |
| Rate limiter reset on every call; bare `except`; swallowed errors | reliability: retries, typed errors |
| Committed `credentials.json` + live token | secrets via env only |
| Over-decomposed sub-agents | start simple; agent vs. workflow by need |

---

## 19. Open items / assumptions

- **Model default:** provider-agnostic; defaults to the existing OpenAI setup, Anthropic a one-line switch. Confirm if you'd rather default to Claude.
- **Render adapter:** fake by default; a real text-to-video integration is M7/optional. Confirm whether you want a real render demoed at all.
- **Repo location:** plan assumes a fresh `curry-nomad/` project (old `api/`+`web/` kept for the before/after contrast). Say if you'd rather rewrite in place.

---

*Ready to build on `go` — starting at M0 (scaffold + config + observability + services/fakes + the Sri Lankan SQLite seed).*
