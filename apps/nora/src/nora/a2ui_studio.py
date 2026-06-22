"""The A2UI "studio" graph — the dynamic-schema generative-UI showcase.

Where the analytics path attaches a FIXED dashboard (AnalyticsDashboard: stats/table/chart), this
graph lets a secondary "UI-author" model COMPOSE the surface: it picks an ordered list of catalog
blocks (heading / text / metrics / chart / table) to fit the answer — the "LLM authors the UI"
(dynamic-schema A2UI) pattern. The surface rides the same native push_ui_message channel as the
dashboard (no second runtime); the /studio web surface renders it with its block catalog.

    START → analytics (subgraph) → ui_author → END

This is the deliberate contrast to the fixed dashboard, mirroring the repo's agent-vs-workflow
split: there the *code* picks the components, here the *model* composes them.
"""

from __future__ import annotations

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.ui import push_ui_message

from nora.analytics.graph import build_analytics_graph
from nora.config import Settings, get_settings
from nora.observability import get_logger
from nora.orchestrator import _sql_results_from_messages
from nora.schemas import A2uiSurface, Context
from nora.state import OrchestratorState

log = get_logger(__name__)

AUTHOR_INSTRUCTIONS = (
    "Compose a UI to present this analytics answer to a Sri Lankan spice-business operator. YOU "
    "choose the layout: emit an ordered list of blocks (each block sets `type` and only the fields "
    "that type uses) that best fits the data.\n"
    "- type 'heading': set `text` to a short surface title.\n"
    "- type 'text': set `text` to one sentence of explanation or insight.\n"
    "- type 'metrics': set `metrics` to a row of KPI tiles (each label + pre-formatted value, "
    "optional trend 'up'/'down'/'neutral' with a trend_value like '+12%').\n"
    "- type 'chart': set `title`, `chart_kind` ('bar' for ranking/comparison, 'line' for a trend "
    "over time, 'pie' for part-of-whole), and `series` (a list of {label, value}).\n"
    "- type 'table': set `columns` and `rows` (stringified cells), for detail.\n"
    "Lead with a heading, then the most decision-relevant block; add a chart whenever the data has "
    "a natural shape. Keep it tight (2-5 blocks). If the answer isn't data-worthy, return no blocks."
)


def _author_surface(model, answer: str, query_results: str) -> A2uiSurface | None:
    """Best-effort LLM-authored surface from the answer + the SQL the agent ran. Returns None (and
    the caller renders nothing) on failure or a non-data answer — generative UI is never
    load-bearing for the text answer."""
    if not answer.strip():
        return None
    context = f"Answer:\n{answer}"
    if query_results:
        context += f"\n\nQuery results the answer is based on:\n{query_results[:2000]}"
    try:
        surface: A2uiSurface = model.with_structured_output(A2uiSurface).invoke(
            [SystemMessage(content=AUTHOR_INSTRUCTIONS), HumanMessage(content=context)]
        )
    except Exception as exc:  # noqa: BLE001 — optional generative UI: never break the text answer
        log.info("a2ui.skipped", error=str(exc))
        return None
    if not surface.blocks:
        return None
    log.info("a2ui.authored", blocks=len(surface.blocks))
    return surface


def build_a2ui_graph(
    *,
    settings: Settings | None = None,
    analytics_graph=None,
    author_model=None,
    checkpointer=None,
    store=None,
):
    """Compile the studio graph. `analytics_graph`/`author_model` are injectable for offline tests;
    by default they're built from settings (and the platform injects checkpointer/store)."""
    settings = settings or get_settings()
    if analytics_graph is None:
        analytics_graph = build_analytics_graph(settings=settings, store=store)
    if author_model is None:
        # with_structured_output call whose result never lands in `messages` → disable_streaming for
        # the same reason as the dashboard model (orchestrator.py). No key → authoring is simply off.
        try:
            author_model = init_chat_model(settings.model, temperature=0, disable_streaming=True)
        except Exception:  # noqa: BLE001 — no key → no authored surface, the answer still streams
            author_model = None

    def ui_author(state: OrchestratorState) -> dict:
        # Runs right after the analytics subgraph (its run_sql steps + streamed answer are already
        # inline). Compose the surface from the final answer + the SQL the agent saw, and push it on
        # the generative-UI channel (the /studio UI renders it via its block catalog).
        if author_model is None:
            return {}
        messages = state["messages"]
        final = messages[-1]
        answer = final.content if isinstance(final.content, str) else str(final.content)
        surface = _author_surface(author_model, answer, _sql_results_from_messages(messages))
        if surface is None:
            return {}
        push_ui_message("a2ui_surface", surface.model_dump(), message=final)
        return {"messages": [final]}  # same id → no-op merge; mirrors the analytics_dashboard node

    builder = StateGraph(OrchestratorState, context_schema=Context)
    builder.add_node("analytics", analytics_graph)
    builder.add_node("ui_author", ui_author)
    builder.add_edge(START, "analytics")
    builder.add_edge("analytics", "ui_author")
    builder.add_edge("ui_author", END)
    return builder.compile(checkpointer=checkpointer, store=store)


def make_a2ui_graph():
    """Platform factory (Aegra via aegra.json) — Postgres checkpointer + semantic Store injected at
    runtime, exactly like make_graph() in orchestrator.py. Requires provider keys (builds models)."""
    return build_a2ui_graph(settings=get_settings())
