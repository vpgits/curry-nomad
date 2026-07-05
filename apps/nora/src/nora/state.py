"""Graph state definitions (TypedDict only).

LangGraph state is a TypedDict with optional reducers on fields. The two reducers used:
  - `add_messages` — message-aware merge for chat history.
  - `operator.add` — list concatenation, the fan-in primitive for parallel branches
    (parallel ideation and the Send-based per-shot prompt workers both append here).

TypedDict (not Pydantic) is used deliberately: it is required by `create_agent` and is the
clean choice for `StateGraph` partial-update semantics.

**State holds JSON-native data (dicts), not Pydantic models.** The structured-output schemas
(`RouteDecision`, `ConceptIdea`, …) are used *transiently inside nodes* for validation and typed
logic, then `.model_dump()`-ed before being written to state. This keeps persistence portable:
a checkpointer serializes state at every super-step, and the platform (Aegra)
injects its own checkpointer whose msgpack serializer only deserializes *allow-listed* modules.
Custom Pydantic types stored there round-trip as bare dicts under `LANGGRAPH_STRICT_MSGPACK=true`
(and a future LangGraph default), silently breaking attribute access on resume. Dicts dodge that
entirely; nodes rehydrate (`Model(**d)`) where they need the typed object — see
`marketing/nodes.py`.
"""

from __future__ import annotations

import operator
from collections.abc import Sequence
from typing import Annotated, NotRequired, TypedDict

from langgraph.graph.message import MessagesState, add_messages
from langgraph.graph.ui import AnyUIMessage, ui_message_reducer
from langgraph.managed import RemainingSteps


def reset_or_extend(current: list, update) -> list:
    """Reducer for a fan-in list that also has to be *resettable* across loop iterations.

    Within one superstep it extends (gathering parallel `Send` worker outputs, like
    `operator.add`). But the evaluator-optimizer loop re-runs the storyboard → shot fan-out on
    each revision, so before regenerating we must clear stale prompts. Returning `None` from a
    node resets the list to empty; returning a list extends it.
    """
    if update is None:
        return []
    return (current or []) + list(update)


class OrchestratorState(MessagesState):
    """Top-level router state.

    Extends `MessagesState`, which contributes the `messages` channel and its `add_messages`
    reducer — the chat history the `nora` graph serves to the useStream client. `handoff` and `ui`
    are our own additions; both are JSON-native (a dict and a list of dicts), so checkpoints still
    survive strict msgpack (see the module docstring)."""

    # The supervisor's latest delegation: {"target": "marketing", "task": ..., "product_hint": ...}.
    # A capability node reads it for the task/hint the supervisor handed it (e.g. marketing).
    handoff: NotRequired[dict]
    # Generative-UI channel: the analytics node push_ui_message()-es a dashboard here, which the
    # useStream UI renders via LoadExternalComponent. (UIMessage is a plain dict — msgpack-safe.)
    ui: Annotated[Sequence[AnyUIMessage], ui_message_reducer]


class AnalyticsState(TypedDict):
    """Analytics agent subgraph state — the running message thread plus the step budget.

    `remaining_steps` is a LangGraph *managed* value (auto-populated from the run's recursion_limit,
    no manual seeding). The llm node reads it to stop gracefully with a plain answer when the budget
    is nearly spent, rather than looping into a `GraphRecursionError` — which, since analytics runs as
    a subgraph node, would otherwise crash the whole turn. (The workspace agent reuses this state, so
    it gets the same guard.)

    `ui` mirrors the orchestrator's channel (same name + `ui_message_reducer`): the analytics agent's
    `present_ui` tool (ui_tools.py) pushes an `A2uiSurface` card from INSIDE this subgraph, and a card
    written to an undeclared channel is silently dropped. Because analytics runs as a real subgraph
    node, sharing the channel name makes LangGraph propagate those cards up into the orchestrator's
    `ui` channel exactly like `messages` — so an agent-authored card renders inline in the top-level
    thread. (The workspace loops reuse this state too, so they carry the channel; their imperative node
    re-emits instead — see ui_tools.emit_present_ui_from_messages.)"""

    messages: Annotated[list, add_messages]
    remaining_steps: RemainingSteps
    ui: Annotated[Sequence[AnyUIMessage], ui_message_reducer]


class MarketingState(TypedDict):
    """Marketing workflow subgraph state."""

    # Every structured field is the schema's `.model_dump()` dict, not the model itself (see the
    # module docstring). Nodes rehydrate via `Model(**d)` where they need typed access.
    request: str
    product_hint: str | None
    product_facts: NotRequired[dict]  # the chosen product's real DB row (grounding)
    brand_voice: str
    concepts: Annotated[list[dict], operator.add]  # ConceptIdea dicts; parallel ideate (gather)
    chosen_concept: NotRequired[dict]  # ConceptIdea
    # Operator-controlled post size + caption verbosity (set at the copy-review gate, seeded from
    # settings when absent). `num_images` unifies the on-screen-text lines, storyboard shots, and
    # rendered stills so the count is always consistent.
    num_images: NotRequired[int]
    verbosity: NotRequired[str]  # concise | standard | detailed
    post_copy: NotRequired[dict]  # {"caption": str, "on_screen_texts": list[str]}
    approved: NotRequired[bool]
    shots: NotRequired[list[dict]]  # Shot
    # Send fan-in (gather), but resettable so revisions don't accumulate stale prompts.
    shot_prompts: Annotated[list[dict], reset_or_extend]  # ShotPrompt
    critique: NotRequired[dict]  # Critique
    revision_count: NotRequired[int]  # seeded by initial_marketing_state; nodes read it defensively
    brief: NotRequired[dict]  # PostBrief
    # Staged render: `render_stills` holds the generated stills while the operator reviews them at
    # the still-review HITL gate; `still_regen` carries the operator's re-roll request into the
    # regenerate node; `still_revision_count` bounds the loop; `render_result` is the finalized
    # Instagram post the marketing_render card renders.
    render_stills: NotRequired[dict]  # RenderResult (status="stills_ready") awaiting review
    still_regen: NotRequired[dict]  # {"indices": [...], "overrides": {index: prompt}}
    still_revision_count: NotRequired[int]
    render_result: NotRequired[dict]
