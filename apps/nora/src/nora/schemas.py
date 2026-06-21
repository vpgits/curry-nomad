"""Typed contracts for everything the LLMs read or write.

Structured outputs (router decisions, concepts, scripts, the final VideoBrief) are Pydantic
models — the model is forced to fill these shapes, which keeps the workflow deterministic and
makes the marketing evals possible. `Context` is the per-run dataclass injected into nodes via
`context_schema` (LangGraph requires a dataclass/TypedDict here, not a Pydantic model).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

# --- Router ---------------------------------------------------------------------------


class RouteDecision(BaseModel):
    """The orchestrator's classification of an incoming request."""

    capability: Literal["analytics", "marketing", "clarify"]
    reason: str
    product_hint: str | None = None  # product name/id if a marketing request references one


# --- Marketing creative contracts -----------------------------------------------------


class ConceptIdea(BaseModel):
    angle: str
    hook: str
    rationale: str


class ScriptBeat(BaseModel):
    t_start_s: float
    t_end_s: float
    voiceover: str
    on_screen_text: str | None = None


class Shot(BaseModel):
    index: int
    scene_description: str
    duration_s: float


class ShotPrompt(BaseModel):
    index: int
    t2v_prompt: str  # the text-to-video generation prompt for this shot


class Critique(BaseModel):
    """Evaluator verdict in the evaluator-optimizer loop."""

    passed: bool
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class VideoBrief(BaseModel):
    """The final creative package the marketing workflow produces."""

    product_name: str
    concept: str
    hook: str
    target_duration_s: float
    platform: str = "instagram_reel"
    script_beats: list[ScriptBeat]
    shots: list[Shot]
    shot_prompts: list[ShotPrompt]
    cta: str
    music_mood: str
    hashtags: list[str]
    product_facts_used: list[str]  # for the grounding eval


# --- Analytics generative-UI dashboard ------------------------------------------------


class DashboardStat(BaseModel):
    """A single headline metric for the analytics dashboard."""

    label: str
    value: str  # pre-formatted (e.g. "LKR 105,850", "73", "4.2%")
    hint: str | None = None  # optional sub-label / context


class DashboardTable(BaseModel):
    """An optional small results table (stringified cells for display)."""

    columns: list[str]
    rows: list[list[str]]


class AnalyticsDashboard(BaseModel):
    """A compact dashboard composed from an analytics answer — the generative-UI payload.

    Built post-hoc from the agent's final answer (+ its last query result) and rendered two ways:
    the useStream UI consumes it via push_ui_message/LoadExternalComponent; the CopilotKit UI via
    A2UI surfaces. `stats` empty + no `table` means "nothing dashboard-worthy" → skip rendering."""

    title: str
    stats: list[DashboardStat] = Field(default_factory=list)
    table: DashboardTable | None = None


# --- Runtime context (per-run; injected via context_schema) ---------------------------


@dataclass
class Context:
    user_id: str = "arun"  # single demo user; namespaces the store
    model: str | None = None  # optional per-run model override
