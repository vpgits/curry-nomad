"""Tests for the generative-UI additions.

Offline, with the same scripted fakes as the other suites:
- The marketing concept-pick gate (`auto_choose=False`): the parallel ideation becomes an
  interactive HITL selection — interrupt with N concepts, resume with the chosen index.
- The analytics dashboard's chosen chart: `_build_dashboard` keeps a chart-only dashboard (the
  "agent picks the visualization" payload) and the chart survives the model_dump → UI hop.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from nora.analytics.graph import build_analytics_graph
from nora.config import Settings
from nora.marketing.graph import build_marketing_graph, initial_marketing_state
from nora.orchestrator import _build_dashboard, build_orchestrator
from nora.schemas import (
    A2uiBlock,
    A2uiSurface,
    AnalyticsDashboard,
    ChartPoint,
    DashboardChart,
    VideoBrief,
)
from nora.services.renderer import OpenRouterRenderer
from tests.fakes import (
    FakeOpenRouterClient,
    ScriptedChatModel,
    ScriptedStructuredModel,
    ai_final,
    ai_tool_call,
)
from tests.test_marketing_graph import _passing_model

# --- marketing: interactive concept-pick gate -----------------------------------------


def _concept_graph(thread: str):
    """Marketing graph with the concept gate ON but the script gate auto-approved, so a run
    pauses exactly once — at the concept pick — then finishes after resume."""
    graph = build_marketing_graph(
        model=_passing_model(), checkpointer=InMemorySaver(), auto_choose=False, auto_approve=True
    )
    return graph, {"configurable": {"thread_id": thread}}


def test_concept_pick_interrupts_with_the_concepts():
    graph, cfg = _concept_graph("concept-1")
    result = graph.invoke(initial_marketing_state("reel", "Cloves"), cfg)
    assert "__interrupt__" in result
    payload = graph.get_state(cfg).interrupts[0].value
    assert payload["kind"] == "concept_pick"  # distinguishes it from the script-review gate
    assert len(payload["concepts"]) == 3  # the parallel ideation, surfaced for selection
    assert "brief" not in graph.get_state(cfg).values  # paused before any creative compute


def test_concept_pick_resume_selects_the_chosen_index():
    graph, cfg = _concept_graph("concept-2")
    graph.invoke(initial_marketing_state("reel", "Cloves"), cfg)
    # _passing_model scripts concepts angle 0..2; pick index 2 and it must drive the brief.
    result = graph.invoke(Command(resume={"chosen_index": 2}), cfg)
    assert VideoBrief(**result["brief"]).concept == "angle 2"


def test_concept_pick_out_of_range_falls_back_to_first():
    graph, cfg = _concept_graph("concept-3")
    graph.invoke(initial_marketing_state("reel", "Cloves"), cfg)
    result = graph.invoke(Command(resume={"chosen_index": 99}), cfg)  # bogus index
    assert VideoBrief(**result["brief"]).concept == "angle 0"


def test_auto_choose_default_keeps_a_single_script_gate():
    """Default auto_choose=True must NOT add a concept interrupt — the only gate is script review.
    This is what keeps every unattended caller (evals, the other tests) unchanged."""
    graph = build_marketing_graph(model=_passing_model(), checkpointer=InMemorySaver())
    result = graph.invoke(initial_marketing_state("reel", "Cloves"), {"configurable": {"thread_id": "auto-c"}})
    payload = result["__interrupt__"][0].value
    assert payload["kind"] == "script_review"


def _marketing_supervisor():
    """A supervisor that delegates a Cloves video ad, then ends silently when marketing returns."""
    return ScriptedChatModel(
        [
            ai_tool_call(
                "to_marketing", {"task": "make an ad for Cloves", "product_hint": "Cloves"}, "h1"
            ),
            ai_final(""),
        ]
    )


def _stub_analytics(*args, **kwargs):  # noqa: ARG001
    raise AssertionError("analytics must not run on a marketing request")


def test_orchestrator_chains_concept_then_script_gates():
    """The live /ask marketing path: with auto_choose=False the orchestrator now pauses TWICE —
    first at the concept pick, then at the script review — and resumes both on one thread."""
    orch = build_orchestrator(
        supervisor_model=_marketing_supervisor(),
        analytics_graph=_stub_analytics,
        marketing_graph=build_marketing_graph(
            model=_passing_model(), auto_approve=False, auto_choose=False
        ),
        checkpointer=InMemorySaver(),
    )
    cfg = {"configurable": {"thread_id": "two-gates"}}

    r1 = orch.invoke({"messages": [HumanMessage("make an ad for Cloves")]}, cfg)
    assert "__interrupt__" in r1
    assert orch.get_state(cfg).interrupts[0].value["kind"] == "concept_pick"

    r2 = orch.invoke(Command(resume={"chosen_index": 1}), cfg)  # pick concept 1
    assert "__interrupt__" in r2
    assert orch.get_state(cfg).interrupts[0].value["kind"] == "script_review"

    r3 = orch.invoke(Command(resume={"approved": True}), cfg)
    brief = next((u["props"]["brief"] for u in r3.get("ui", []) if u.get("name") == "video_brief"), None)
    assert brief is not None and brief["concept"] == "angle 1"  # the chosen concept drove the brief


def test_marketing_render_card_carries_video_jobs(tmp_path):
    """With the OpenRouter renderer injected, a finished marketing turn pushes a `marketing_render`
    card carrying the hero image, per-shot stills, and the video job ids the UI polls."""
    settings = Settings(media_dir=tmp_path)
    orch = build_orchestrator(
        supervisor_model=_marketing_supervisor(),
        analytics_graph=_stub_analytics,
        marketing_graph=build_marketing_graph(
            model=_passing_model(),
            auto_approve=True,
            renderer=OpenRouterRenderer(settings, client=FakeOpenRouterClient()),
        ),
        checkpointer=InMemorySaver(),
    )
    cfg = {"configurable": {"thread_id": "render-card"}}
    r = orch.invoke({"messages": [HumanMessage("make an ad for Cloves")]}, cfg)

    card = next((u["props"] for u in r.get("ui", []) if u.get("name") == "marketing_render"), None)
    assert card is not None
    assert card["status"] == "rendering"
    assert card["hero_image_url"].startswith("/media/")
    assert card["shots"] and all(s["video_job_id"] for s in card["shots"])


# --- analytics: the chosen chart ------------------------------------------------------


def _chart_dashboard() -> AnalyticsDashboard:
    """A chart-only dashboard: no stats, no table — exercises the has_chart skip-guard."""
    return AnalyticsDashboard(
        title="Revenue by month",
        stats=[],
        table=None,
        chart=DashboardChart(
            kind="line",
            x_label="month",
            y_label="LKR",
            series=[ChartPoint(label="Jan", value=120), ChartPoint(label="Feb", value=150)],
        ),
    )


def test_build_dashboard_keeps_a_chart_only_dashboard():
    model = ScriptedStructuredModel({AnalyticsDashboard: [_chart_dashboard()]})
    dashboard = _build_dashboard(model, answer="Revenue trended up.", query_results="month|rev")
    assert dashboard is not None  # a chart alone is dashboard-worthy
    data = dashboard.model_dump()  # what the orchestrator pushes onto the UI channel
    assert data["chart"]["kind"] == "line"
    assert [p["label"] for p in data["chart"]["series"]] == ["Jan", "Feb"]


def test_build_dashboard_skips_when_chart_kind_is_none():
    empty = AnalyticsDashboard(title="n/a", stats=[], table=None, chart=DashboardChart(kind="none"))
    model = ScriptedStructuredModel({AnalyticsDashboard: [empty]})
    assert _build_dashboard(model, answer="A one-off number.", query_results="") is None


# --- A2UI: the LLM-authored surface (an output MODE of the analytics path, formerly /studio) ------


def test_authored_ui_mode_pushes_an_a2ui_surface():
    """With config.configurable.ui_mode == "authored", the analytics path's dashboard node lets the
    model COMPOSE the surface (the old /studio A2UI showcase, folded into /ask as an output mode) and
    pushes `a2ui_surface` on the ui channel instead of the fixed `analytics_dashboard`."""
    surface = A2uiSurface(
        blocks=[
            A2uiBlock(type="heading", text="Top sellers"),
            A2uiBlock(
                type="chart",
                chart_kind="bar",
                title="Revenue by product",
                series=[ChartPoint(label="Cinnamon", value=500), ChartPoint(label="Cloves", value=300)],
            ),
        ]
    )
    orch = build_orchestrator(
        supervisor_model=ScriptedChatModel(
            [ai_tool_call("to_analytics", {"task": "top sellers"}, "h1"), ai_final("")]
        ),
        analytics_graph=build_analytics_graph(model=ScriptedChatModel([ai_final("Cinnamon leads.")])),
        marketing_graph=object(),  # never invoked on an analytics turn
        # The dashboard node uses this model for BOTH the fixed dashboard and the authored surface;
        # here it returns an A2uiSurface (the authored-mode structured output).
        dashboard_model=ScriptedStructuredModel({A2uiSurface: [surface]}),
        checkpointer=InMemorySaver(),
    )
    result = orch.invoke(
        {"messages": [HumanMessage("top sellers?")]},
        {"configurable": {"thread_id": "a2ui", "ui_mode": "authored"}},
    )
    pushed = [u for u in result.get("ui", []) if u.get("name") == "a2ui_surface"]
    assert pushed, "authored mode must push an a2ui_surface (not the fixed dashboard)"
    blocks = pushed[0]["props"]["blocks"]
    assert [b["type"] for b in blocks] == ["heading", "chart"]  # the model's chosen composition
    assert blocks[1]["chart_kind"] == "bar"
    # And NOT the fixed dashboard card.
    assert not any(u.get("name") == "analytics_dashboard" for u in result.get("ui", []))


# Note: route planning is no longer a chat capability — it lives on the ops REST API + the /routes
# page (its `route_map` card is rendered there directly, not pushed by the orchestrator). The
# deterministic optimizer itself is covered by test_operations_routing.py.
