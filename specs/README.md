# Specs

Read in order. Everything here is build-ready and the LangGraph/LangChain API details are validated against the live docs.

1. [`00_api_contracts.md`](00_api_contracts.md) — the exact, doc-validated LangGraph/LangChain 1.x imports & signatures the code must use (incl. `push_ui_message` generative UI + the Aegra serving layer).
2. [`01_implementation_spec.md`](01_implementation_spec.md) — project structure, module-by-module contracts, the graph wiring, all capabilities, and the cross-cutting concerns. §1–§14 are the original two-capability build; §15–§17 add the operations subsystem and the generative-UI layer.
3. [`02_data_and_evals.md`](02_data_and_evals.md) — the bundled Sri Lankan SQLite schema/seed and the dual evaluation harness (§5 adds the writable operations DB).
4. [`03_milestones.md`](03_milestones.md) — M0–M7 build order with files + acceptance per milestone, then the post-M7 phases (M8 operations/routing, M9 generative UI + A2UI studio).

**Built ≠ original plan.** §1–§14 / M0–M7 describe the initial two-capability build (analytics agent + marketing workflow), served by `langgraph dev`. The codebase has since grown a third, **deterministic** pillar (operations/routing — the "limits of agentic dev"), a **native generative-UI** layer, and moved serving to **Aegra** (`langgraph.json` → `aegra.json`). Those landed as later phases and are appended as marked sections/milestones rather than rewritten in place.

Higher-level context lives in [`../docs/CASE_STUDY_PLAN.md`](../docs/CASE_STUDY_PLAN.md) and the interactive [`../docs/pitch.html`](../docs/pitch.html).

**Build entry point:** start at **M0** in `03_milestones.md`.

> `⚠️ verify` markers flag the few API details to confirm at first touch (e.g. `store=` on `create_agent`, OpenRouter's video API). Everything else is doc-confirmed.
