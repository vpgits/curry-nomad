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
    brand_voice: str
    concepts: Annotated[list[ConceptIdea], operator.add]  # parallel ideate (gather)
    chosen_concept: NotRequired[ConceptIdea]
    script_beats: NotRequired[list[ScriptBeat]]
    approved: NotRequired[bool]
    shots: NotRequired[list[Shot]]
    shot_prompts: Annotated[list[ShotPrompt], operator.add]  # Send fan-in (gather)
    critique: NotRequired[Critique]
    revision_count: int
    brief: NotRequired[VideoBrief]
    render_result: NotRequired[dict]
