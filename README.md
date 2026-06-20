# Curry Nomad — an agentic workflows case study

A clean, runnable **LangGraph / LangChain** application built as a teaching artifact: the reference codebase for a ~90-minute hands-on session on **how to build agentic systems properly** — orchestration, the agent loop, deterministic workflows, tools, human-in-the-loop, memory, observability, and evaluation.

> **Status: specs complete, implementation pending.** This repo currently contains the plan + the granular, doc-validated build spec. No application code yet — build it from `specs/` (start at M0).

## The idea

**Nora** is the operations assistant for **Curry Nomad**, a (fictional) Sri Lankan spice business. One orchestrator routes each request to one of two capabilities that deliberately showcase the two paradigms:

- **Analytics — an AGENT.** Answers questions over a bundled SQLite database: writes SQL, runs it, and *self-corrects when a query fails*. (Open-ended → agent loop.)
- **Marketing Studio — a WORKFLOW.** Generates a structured **video-ad creative brief** for a product via a predictable pipeline with a human-review checkpoint. (Predictable → workflow: chaining + evaluator-optimizer + parallel fan-out.)

**Canonical demo:** *"What's our best-selling product in Colombo last quarter?"* → analytics agent answers (self-correcting an error) → *"Make a 30s video ad for it"* → marketing workflow runs, pauses for you to approve the script, finishes.

## Why it's a good teaching vehicle

- **Both paradigms in one app**, under one router → teaches *when to use which*.
- **Evaluation is actually possible**: deterministic ground-truth for the data agent, LLM-as-judge + guardrails for the creative workflow — run live.
- **Self-contained & safe**: one LLM API key, bundled data, no external accounts, no real spend (rendering is a placeholder adapter by default).
- **Provider-agnostic**: model is a config string (`init_chat_model`); swap OpenAI ↔ Anthropic ↔ others in one line.

## Specs (build from these)

| File | What it covers |
|---|---|
| [`specs/00_api_contracts.md`](specs/00_api_contracts.md) | Exact LangGraph/LangChain 1.x imports & signatures, validated against the live docs |
| [`specs/01_implementation_spec.md`](specs/01_implementation_spec.md) | Project structure, module contracts, the graph wiring, both capabilities, memory/HITL/config/services |
| [`specs/02_data_and_evals.md`](specs/02_data_and_evals.md) | The Sri Lankan SQLite schema + seed, and the dual eval harness |
| [`specs/03_milestones.md`](specs/03_milestones.md) | M0–M7 build order, files per milestone, and acceptance criteria |
| [`docs/CASE_STUDY_PLAN.md`](docs/CASE_STUDY_PLAN.md) | The higher-level plan + the 90-min run-of-show |
| [`docs/pitch.html`](docs/pitch.html) | Interactive pitch/visualization deck |

## Stack

LangGraph 1.x · LangChain 1.x · Python 3.12 (uv) · pydantic / pydantic-settings · structlog · LangSmith (tracing + evals) · SQLite · pytest · ruff. Provider-agnostic via `init_chat_model`.

## Running (once built)

```bash
uv sync
cp .env.example .env            # add your provider key(s)
uv run python -m nora.data.seed # build the bundled SQLite DB
uv run python -m nora.app "What was our best-selling product in Colombo last quarter?"
uv run python evals/run_evals.py --suite all
# optional: langgraph dev       # serve the graph + view traces in Studio
```

## Teaching map (concept → where it lives)

| Concept | Lives in |
|---|---|
| Routing | `orchestrator.py` |
| Agent loop + self-correction | `analytics/graph.py` |
| Prompt chaining / evaluator-optimizer / parallel (`Send`) | `marketing/graph.py` |
| Tools & gating by risk | `analytics/tools.py`, `services/` |
| Human-in-the-loop (`interrupt`) | `marketing` `human_review` node |
| Memory: checkpointer + semantic Store | `memory.py` |
| Observability | `observability.py` + LangSmith |
| Evaluation (deterministic + LLM-judge) | `evals/` |
