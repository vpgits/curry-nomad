"""Graph state definitions (TypedDict only).

LangGraph state is a TypedDict with optional reducers on fields. The two reducers used:
  - `add_messages` — message-aware merge for chat history.
  - `operator.add` — list concatenation, the fan-in primitive for parallel branches
    (parallel ideation and the Send-based per-shot prompt workers both append here).

TypedDict (not Pydantic) is used deliberately: it is required by `create_agent` and is the
clean choice for `StateGraph` partial-update semantics.
"""

from __future__ import annotations

import operator
from typing import Annotated, NotRequired, TypedDict

from langgraph.graph.message import add_messages

from nora.schemas import (
    ConceptIdea,
    Critique,
    RouteDecision,
    ScriptBeat,
    Shot,
    ShotPrompt,
    VideoBrief,
)


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


class OrchestratorState(TypedDict):
    """Top-level router state."""

    messages: Annotated[list, add_messages]
    route: NotRequired[RouteDecision]


class AnalyticsState(TypedDict):
    """Analytics agent subgraph state — just the running message thread."""

    messages: Annotated[list, add_messages]


class MarketingState(TypedDict):
    """Marketing workflow subgraph state."""

    request: str
    product_hint: str | None
    product_facts: NotRequired[dict]  # the chosen product's real DB row (grounding)
    brand_voice: str
    concepts: Annotated[list[ConceptIdea], operator.add]  # parallel ideate (gather)
    chosen_concept: NotRequired[ConceptIdea]
    script_beats: NotRequired[list[ScriptBeat]]
    approved: NotRequired[bool]
    shots: NotRequired[list[Shot]]
    # Send fan-in (gather), but resettable so revisions don't accumulate stale prompts.
    shot_prompts: Annotated[list[ShotPrompt], reset_or_extend]
    critique: NotRequired[Critique]
    revision_count: int
    brief: NotRequired[VideoBrief]
    render_result: NotRequired[dict]
