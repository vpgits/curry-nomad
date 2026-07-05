"""Typed contracts for everything the LLMs read or write.

Structured outputs (router decisions, concepts, post copy, the final PostBrief) are Pydantic
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


class Shot(BaseModel):
    index: int
    scene_description: str  # what the still image depicts
    on_screen_text: str | None = None  # short caption/overlay line for this image


class ShotPrompt(BaseModel):
    index: int
    image_prompt: str  # the text-to-image generation prompt for this shot


class Critique(BaseModel):
    """Evaluator verdict in the evaluator-optimizer loop."""

    passed: bool
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class PostBrief(BaseModel):
    """The final creative package the marketing workflow produces: an Instagram image post."""

    product_name: str
    concept: str
    hook: str
    caption: str  # the post caption body (hook first line → origin story → CTA)
    shots: list[Shot]  # the images (each may carry an on-screen text line)
    shot_prompts: list[ShotPrompt]
    cta: str
    hashtags: list[str]
    product_facts_used: list[str]  # for the grounding eval


# --- Marketing render (real image generation via OpenRouter) --------------------------
#
# What the OpenRouterRenderer produces from a finished PostBrief: a hero image + a still per shot,
# generated synchronously via OpenRouter `/images`. Together they make up the Instagram post,
# rendered over the same push_ui_message channel as the other marketing cards.


class RenderShot(BaseModel):
    """One shot rendered as a still image for the Instagram post."""

    index: int
    scene_description: str
    image_prompt: str  # the text-to-image generation prompt for this shot
    image_url: str | None = None  # served still, or None if image gen failed
    error: str | None = None


class RenderResult(BaseModel):
    """The renderer's output (the `render_result` in marketing state + the `marketing_render` card).

    `status`: placeholder (no render) | stills_ready (images generated, awaiting the human review
    gate) | rendered (approved/finalized post) | cancelled | error. `render_id` is the media
    sub-directory the stills were written to, so a regenerate pass can reuse it across the
    still-review loop."""

    status: Literal[
        "placeholder", "stills_ready", "rendered", "cancelled", "error"
    ] = "placeholder"
    hero_image_url: str | None = None
    shots: list[RenderShot] = Field(default_factory=list)
    image_model: str | None = None
    render_id: str | None = None
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
# list of catalog blocks to fit the answer — it authors the surface. Pushed as the `a2ui_surface`
# card over the native push_ui_message channel (the analytics path's "Author UI" output mode) and
# rendered by the web `A2uiSurfaceView`. A small, typed block vocabulary keeps this reliable for
# structured output (vs. an arbitrary recursive component tree).


class A2uiMetric(BaseModel):
    label: str
    value: str  # pre-formatted
    trend: Literal["up", "down", "neutral"] | None = None
    trend_value: str | None = None


class A2uiField(BaseModel):
    """One label→value detail row in a `fields` block — the natural way to render a single record or
    entity as a card (a calendar event's Title/When/Where, an order's Id/Customer/Total, an email's
    From/Subject/Date). `value` is pre-formatted text."""

    label: str
    value: str


class A2uiBlock(BaseModel):
    """One block of an authored surface. `type` selects which fields are used:
    heading/text → text; metrics → metrics; fields → fields; chart → title + chart_kind + series;
    table → columns + rows.

    Deliberately ONE flat model (with optional per-type fields), NOT a discriminated union: OpenAI's
    strict structured-output mode rejects anyOf/oneOf/discriminator, so a union here makes the
    authoring call throw (and the surface silently never renders). This mirrors AnalyticsDashboard,
    whose flat optional fields are proven to work with with_structured_output."""

    type: Literal["heading", "text", "metrics", "fields", "chart", "table"]
    text: str | None = None  # heading / text
    metrics: list[A2uiMetric] | None = None  # metrics
    fields: list[A2uiField] | None = None  # fields (label→value detail rows for one record/entity)
    title: str | None = None  # chart / a title above a fields or table block
    chart_kind: Literal["bar", "line", "pie"] | None = None  # chart
    series: list[ChartPoint] | None = None  # chart
    columns: list[str] | None = None  # table
    rows: list[list[str]] | None = None  # table


class A2uiSurface(BaseModel):
    """An LLM-authored UI surface: an ordered list of catalog blocks the model composes per query."""

    blocks: list[A2uiBlock] = Field(default_factory=list)


class ApprovalField(BaseModel):
    """One field in an AI-authored HITL approval card. The model picks the `label` and which tool-call
    argument supplies the value (`arg_key`) and how to show it (`style`) — but the VALUE itself is
    filled from the literal tool args by code, never by the model. So the model authors the *layout*
    while the approver always sees exactly what will run (faithful by construction)."""

    label: str  # human label, e.g. "To", "Subject", "Body", "When"
    arg_key: str  # which tool-call arg supplies the value (e.g. "to", "subject", "body")
    style: Literal["inline", "block"] = "inline"  # inline = short value; block = long text (e.g. a body)


class ApprovalLayout(BaseModel):
    """An AI-authored layout for a pending workspace WRITE action's approval card. The model chooses
    an icon, a short title, and an ordered set of fields appropriate to the action (send email →
    To/Subject/Body; create event → Title/When/Attendees). Values are injected from the literal args,
    and any arg the layout omits is appended by code, so nothing that will run is hidden. Flat optional
    fields (no unions) for the same strict structured-output reason as A2uiBlock."""

    icon: Literal["email", "calendar", "document", "generic"] = "generic"
    title: str  # e.g. "Send email", "Draft email", "Create calendar event"
    fields: list[ApprovalField] = Field(default_factory=list)


# --- Runtime context (per-run; injected via context_schema) ---------------------------


@dataclass
class Context:
    # Operator identity is NOT carried here — it comes from the server-injected auth object via
    # `memory.resolve_user_id` (never a client-settable field). The old `user_id` default lived here
    # with a "namespaces the store" comment but was dead code; namespacing is done from the verified
    # identity, full stop.
    model: str | None = None  # optional per-run model override
