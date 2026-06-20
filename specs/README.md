# Specs

Read in order. Everything here is build-ready and the LangGraph/LangChain API details are validated against the live docs.

1. [`00_api_contracts.md`](00_api_contracts.md) — the exact, doc-validated LangGraph/LangChain 1.x imports & signatures the code must use.
2. [`01_implementation_spec.md`](01_implementation_spec.md) — project structure, module-by-module contracts, the graph wiring, both capabilities, and all cross-cutting concerns.
3. [`02_data_and_evals.md`](02_data_and_evals.md) — the bundled Sri Lankan SQLite schema/seed and the dual evaluation harness.
4. [`03_milestones.md`](03_milestones.md) — M0–M7 build order with files and acceptance criteria per milestone.

Higher-level context lives in [`../docs/CASE_STUDY_PLAN.md`](../docs/CASE_STUDY_PLAN.md) and the interactive [`../docs/pitch.html`](../docs/pitch.html).

**Build entry point:** start at **M0** in `03_milestones.md`.

> `⚠️ verify` markers flag the few API details to confirm at first touch (e.g. `store=` on `create_agent`, OpenRouter's video API). Everything else is doc-confirmed.
