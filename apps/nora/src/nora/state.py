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
a checkpointer serializes state at every super-step, and the platform (`langgraph dev`)
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
    reducer — the chat history the `nora` graph serves to the useStream client. `route` and `ui`
    are our own additions; both are JSON-native (a dict and a list of dicts), so checkpoints still
    survive strict msgpack (see the module docstring)."""

    route: NotRequired[dict]  # RouteDecision.model_dump()
    # Generative-UI channel: the analytics node push_ui_message()-es a dashboard here, which the
    # useStream UI renders via LoadExternalComponent. (UIMessage is a plain dict — msgpack-safe.)
    ui: Annotated[Sequence[AnyUIMessage], ui_message_reducer]


class AnalyticsState(TypedDict):
    """Analytics agent subgraph state — just the running message thread."""

    messages: Annotated[list, add_messages]


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
    script_beats: NotRequired[list[dict]]  # ScriptBeat
    approved: NotRequired[bool]
    shots: NotRequired[list[dict]]  # Shot
    # Send fan-in (gather), but resettable so revisions don't accumulate stale prompts.
    shot_prompts: Annotated[list[dict], reset_or_extend]  # ShotPrompt
    critique: NotRequired[dict]  # Critique
    revision_count: int
    brief: NotRequired[dict]  # VideoBrief
    render_result: NotRequired[dict]
