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

    capability: Literal["analytics", "marketing", "routing", "workspace", "clarify"]
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


# --- Marketing render (real media generation via OpenRouter) --------------------------
#
# What the OpenRouterRenderer produces from a finished VideoBrief: a hero image, a still per shot,
# and (async) one video job per shot. Images are generated synchronously; videos are submitted as
# OpenRouter jobs and polled from the UI, so each shot carries its job id rather than a finished
# URL. Rendered over the same push_ui_message channel as the other marketing cards.


class RenderShot(BaseModel):
    """One storyboard shot's rendered assets. `image_url` is ready immediately; the video is a
    pending OpenRouter job the UI polls (`video_job_id`) until it completes."""

    index: int
    scene_description: str
    t2v_prompt: str
    image_url: str | None = None  # served still (first frame), or None if image gen failed
    video_job_id: str | None = None  # OpenRouter /videos job id, or None if submission failed
    error: str | None = None


class RenderResult(BaseModel):
    """The renderer's output (the `render_result` in marketing state + the `marketing_render` card).

    `status`: placeholder (no render) | rendering (jobs submitted, UI polls) | rendered (sync-only)
    | cancelled | error. `mode` records whether videos are first-frame-conditioned (`image_to_video`,
    when a public media URL is configured) or `text_to_video` (the local fallback)."""

    status: Literal["placeholder", "rendering", "rendered", "cancelled", "error"] = "placeholder"
    mode: Literal["image_to_video", "text_to_video", "none"] = "none"
    hero_image_url: str | None = None
    shots: list[RenderShot] = Field(default_factory=list)
    image_model: str | None = None
    video_model: str | None = None
    detail: str = ""


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


class ChartPoint(BaseModel):
    """One (label, value) datum in a dashboard chart series."""

    label: str
    value: float


class DashboardChart(BaseModel):
    """An optional chart for the dashboard. The builder model *chooses* the kind that fits the
    shape of the data (the canonical "agent picks the visualization" generative-UI move).
    `kind='none'` (or an empty series) renders no chart."""

    kind: Literal["bar", "line", "pie", "none"] = "none"
    x_label: str | None = None  # category axis label (bar/line)
    y_label: str | None = None  # value axis label (bar/line)
    series: list[ChartPoint] = Field(default_factory=list)


class AnalyticsDashboard(BaseModel):
    """A compact dashboard composed from an analytics answer — the generative-UI payload.

    Built post-hoc from the agent's final answer (+ its last query result) and rendered by the
    useStream UI via push_ui_message/LoadExternalComponent. Empty `stats` + no `table` + no chart
    means "nothing dashboard-worthy" → skip rendering."""

    title: str
    stats: list[DashboardStat] = Field(default_factory=list)
    table: DashboardTable | None = None
    chart: DashboardChart | None = None


# --- A2UI-style authored surface (the dynamic-schema "LLM authors the UI" showcase) ----
#
# Unlike AnalyticsDashboard (a fixed stats/table/chart layout), here the model COMPOSES an ordered
# list of catalog blocks to fit the answer — it authors the surface. Rendered over the native
# push_ui_message channel by the /studio surface's catalog. A small, typed block vocabulary keeps
# this reliable for structured output (vs. an arbitrary recursive component tree).


class A2uiMetric(BaseModel):
    label: str
    value: str  # pre-formatted
    trend: Literal["up", "down", "neutral"] | None = None
    trend_value: str | None = None


class A2uiBlock(BaseModel):
    """One block of an authored surface. `type` selects which fields are used:
    heading/text → text; metrics → metrics; chart → title + chart_kind + series; table → columns + rows.

    Deliberately ONE flat model (with optional per-type fields), NOT a discriminated union: OpenAI's
    strict structured-output mode rejects anyOf/oneOf/discriminator, so a union here makes the
    authoring call throw (and the surface silently never renders). This mirrors AnalyticsDashboard,
    whose flat optional fields are proven to work with with_structured_output."""

    type: Literal["heading", "text", "metrics", "chart", "table"]
    text: str | None = None  # heading / text
    metrics: list[A2uiMetric] | None = None  # metrics
    title: str | None = None  # chart
    chart_kind: Literal["bar", "line", "pie"] | None = None  # chart
    series: list[ChartPoint] | None = None  # chart
    columns: list[str] | None = None  # table
    rows: list[list[str]] | None = None  # table


class A2uiSurface(BaseModel):
    """An LLM-authored UI surface: an ordered list of catalog blocks the model composes per query."""

    blocks: list[A2uiBlock] = Field(default_factory=list)


# --- Runtime context (per-run; injected via context_schema) ---------------------------


@dataclass
class Context:
    user_id: str = "arun"  # single demo user; namespaces the store
    model: str | None = None  # optional per-run model override
