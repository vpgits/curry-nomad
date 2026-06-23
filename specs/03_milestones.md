# Milestones — files & acceptance

> Each milestone leaves the repo runnable and maps to a segment of the 90-minute session. Build in order. "Acceptance" = the concrete check that the milestone is done.

## M0 — Scaffold & foundations
**Files:** `pyproject.toml`, `.env.example`, `src/nora/config.py`, `observability.py`, `schemas.py`, `state.py`, `memory.py`, `services/interfaces.py`, `services/spice_db.py`, `services/renderer.py`, `data/seed.py`, `tests/test_spice_db.py`.
**Acceptance:**
- `uv sync` installs; `uv run python -m nora.data.seed` produces `curry_nomad.db` deterministically (re-run → identical).
- `pytest tests/test_spice_db.py` green: a known query returns expected rows; `run_sql` rejects non-SELECT / chained statements; enforces LIMIT; raises `SqlError` on bad SQL.
- `get_logger().info("hello")` emits structured JSON; `get_settings()` loads from env.

## M1 — Analytics agent (the AGENT loop)
**Files:** `analytics/tools.py`, `analytics/prompts.py`, `analytics/graph.py`, `app.py` (analytics path), `tests/test_tools.py`, `tests/test_analytics_graph.py`.
**Acceptance:**
- `python -m nora.app "What was our best-selling product in Colombo last quarter?"` returns the correct product (matches `reference_sql`).
- A "tricky" question triggers a wrong-column query → `sql.error` logged → agent repairs → correct answer (self-correction works).
- `should_continue` loop terminates; `ToolNode(handle_tool_errors=...)` converts a raised `SqlError` into a `ToolMessage`.
- If `LANGSMITH_TRACING=true`, a trace shows the llm↔tools loop.

## M2 — Marketing workflow (the WORKFLOW)
**Files:** `marketing/prompts.py`, `marketing/nodes.py`, `marketing/graph.py`, `tests/test_marketing_graph.py`.
**Acceptance:**
- Running the marketing subgraph for a product yields a valid `VideoBrief` (passes the M-suite guardrails).
- `ideate` produces `marketing_num_concepts` concepts in parallel; `len(shot_prompts) == len(shots)` (Send fan-out/fan-in works).
- The evaluator-optimizer loop runs and is bounded by `marketing_max_revisions`.
- `render` returns the placeholder result (no external call).

## M3 — HITL + memory
**Files:** add `human_review` interrupt to `marketing/graph.py`; `memory.seed_brand_knowledge`; wire `runtime.store` reads into analytics (`DEFINITIONS`) and marketing (`BRAND`).
**Acceptance:**
- Running marketing pauses at `human_review`: `stream.interrupts` is non-empty; resuming with `Command(resume={"approved":True})` proceeds; `{"approved":False}` routes to cancel; an edited script is honored.
- Interrupt requires the checkpointer + `thread_id` (removing it surfaces a clear error) and is called exactly once per node.
- Adding a metric definition to the Store (e.g. "revenue = net of refunds") changes the analytics answer for a revenue question (memory actually shapes behavior).
- Brand voice from the Store visibly shapes the generated script.

## M4 — Orchestrator (routing) + end-to-end
**Files:** `orchestrator.py`, finalize `app.py`, `langgraph.json`, `tests/test_router.py`.
**Acceptance:**
- A data question routes to analytics; "make a 30s video ad for it" routes to marketing carrying `product_hint`; an ambiguous request hits `clarify`.
- The **canonical demo flow** works on one `thread_id`: ask for the top product → agent answers → "make a video ad for it" → workflow runs, pauses for review, finishes.
- `langgraph dev` serves the `nora` graph (Studio shows the graph + traces).

## M5 — Evaluation harness
**Files:** `evals/analytics_dataset.jsonl`, `evals/marketing_dataset.jsonl`, `evals/evaluators.py`, `evals/run_evals.py`.
**Acceptance:**
- `python evals/run_evals.py --suite all` runs **offline** (bundled DB), prints per-item results + summary metrics.
- Analytics: derived-truth comparison works; recovery items measured. Marketing: guardrails + judge run; HITL auto-approved in eval mode.
- Metrics meet the §3 targets in `02_data_and_evals.md` (or document the gap).

## M6 — Tests, docs, polish
**Files:** complete `tests/`, `README.md` (teaching map + run-of-show + how-to-run), prompt cleanup in `prompts.py`, ruff config.
**Acceptance:**
- `pytest` green; `ruff check .` clean.
- README maps each concept → file → demo segment; documents `.env` setup and the provider switch.
- No secrets committed; `.gitignore` covers `.env`, `__pycache__`, etc. (DB seed is intentionally committed).

## M7 — Optional: real adapters (the "production I/O" coda)
**Files:** `OpenRouterRenderer` + `services/openrouter.py` (now **implemented** — see §18 of `01_implementation_spec.md`); ops-api `/media` serving; web render card + video proxy routes; document `SqliteSaver`/`PostgresStore` swaps.
**Acceptance:**
- `NORA_RENDERER=openrouter` (+ `OPENROUTER_API_KEY`) generates a hero image + per-shot stills and submits one image→video job per shot; the `marketing_render` card polls each and swaps in the video. Falls back to text→video unless `NORA_MEDIA_PUBLIC_BASE_URL` is set (OpenRouter needs a public first-frame URL). The full test suite stays **offline** (the OpenRouter client is injected as a fake).
- Swapping `InMemorySaver`→`SqliteSaver` and `InMemoryStore`→`PostgresStore` is a config/wiring change only (no graph changes) — demonstrates ports & adapters.

---

# Post-M7 phases (built after the original plan)

> M0–M7 above are the original two-capability build. The milestones below were added later and extend the same architecture; they're the "limits of agentic dev" pillar and the generative-UI layer. (The serving layer also moved from `langgraph dev` to **Aegra** — a self-hosted Agent Protocol backend, Postgres-backed; `langgraph.json` → `aegra.json`. Graph code is unchanged.)

## M8 — Operations subsystem + the `routing` capability (the "limits of agentic dev" pillar)
**Files:** `operations/{errors,interfaces,models,schema,store,services,geo,routing,seed,api}.py`; a `routing` node + `_plan_route_via_ops_api` in `orchestrator.py`; `RouteDecision` gains `"routing"`; the `operations` extra in `pyproject.toml`; `tests/test_operations_{services,routing,seed,api}.py`.
**Acceptance:**
- `python -m nora.operations.seed` builds the **writable** ops DB deterministically (fixed RNG, no wall-clock → re-run is byte-identical), kept separate from the read-only `curry_nomad.db`; it plants a few below-reorder SKUs and a zig-zag delivery set so the demos have signal.
- The services own every invariant: `create_order` rejects an oversell, `adjust_stock` can't drive stock below zero, and every mutation is one atomic `tx()` + a stock-ledger entry. Rejections raise `OperationsError` (the deliberate analogue of `SqlError`) → the REST layer returns a structured `409`.
- `routing.plan_route` returns an optimized tour (haversine → nearest-neighbor → 2-opt) shorter than the reported `naive_km` baseline, and is deterministic (no `random`/wall-clock).
- The REST API serves stock/orders/routes (`nora-ops-api` on :8000, no LLM); the orchestrator routes "plan today's delivery route" to the `routing` capability, which plans via the ops API.
- `test_operations_*` pass **offline with no fakes** — the layer is deterministic, so it's tested directly against a disposable writable DB.

## M9 — Native generative UI + the A2UI studio
**Files:** `schemas.py` (`AnalyticsDashboard`/`DashboardStat`/`DashboardChart`… and the `A2uiSurface`/`A2uiBlock` families); `analytics_dashboard` node + `push_ui_message` calls in `orchestrator.py`; the marketing card pushes; the `route_map` push (M8); `a2ui_studio.py` (the `nora_a2ui` graph); `aegra.json` (registers the second graph); `apps/web` `LoadExternalComponent` renderers (dashboard, concept/script gates, storyboard/timeline/critique, Leaflet route map, `/studio`); `tests/test_generative_ui.py`.
**Acceptance:**
- An analytics answer attaches an `analytics_dashboard` card (stats/table/chart, with the chart **kind chosen to fit** the data); marketing attaches `video_brief` + `marketing_storyboard`/`_script_timeline`/`_critique`; the `routing` capability attaches a `route_map` (rendered as a Leaflet map).
- Gen-UI is **best-effort**: with no provider key (offline) or a non-dashboard-worthy answer, the card is skipped and the streamed text answer is unaffected.
- Marketing now has **two** HITL gates: `choose_concept` raises an `interrupt` with payload `kind: "concept_pick"`; `human_review` with `kind: "script_review"`. Both default to skip (`auto_choose`/`auto_approve`) so evals/tests keep the single script gate.
- The `nora_a2ui` graph (`analytics → ui_author`) lets a model **author** the surface from a block catalog (`A2uiSurface`); the web `/studio` renders it — the dynamic-schema contrast to the fixed dashboard.
- `test_generative_ui.py` asserts the `push_ui_message` payloads for each card.

---

### Mapping milestones → session segments
| Milestone | Session segment |
|---|---|
| M0 | (pre-built) — referenced in framing |
| M1 | Analytics agent (0:12–0:35) |
| M2 | Marketing workflow (0:35–0:55) |
| M3 + M4 | Orchestrator + HITL + memory (0:55–1:05) |
| M5 | Observability + evals, live (1:05–1:25) |
| M6/M7 | Extensibility + before/after (1:25–1:30) |
| M8 | Operations / "limits of agentic dev" (post-launch) |
| M9 | Generative UI + A2UI studio (post-launch) |
