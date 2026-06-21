"""The orchestrator graph — routing (the entry point).

    START → route → (Command goto) → analytics | marketing | clarify → END

A cheap classifier (router model) decides which capability handles the request, then a
`Command(goto=...)` dispatches to it. The two capabilities are *compiled subgraphs invoked
inside the orchestrator nodes* — passing the node's `config` through means a HITL interrupt
inside the marketing subgraph bubbles up and pauses the whole orchestrator, and a
`Command(resume=...)` on the same thread_id flows back down into it. That's the canonical demo:
ask a data question → get an answer → "make a video ad for it" → pause for review → finish,
all on one thread.
"""

from __future__ import annotations

from typing import Literal

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.ui import push_ui_message
from langgraph.types import Command

from nora.analytics.graph import build_analytics_graph
from nora.config import Settings, get_settings
from nora.marketing.graph import build_marketing_graph, initial_marketing_state
from nora.observability import get_logger
from nora.schemas import AnalyticsDashboard, Context, RouteDecision
from nora.state import OrchestratorState

log = get_logger(__name__)

ROUTER_INSTRUCTIONS = (
    "You route requests for Nora, Curry Nomad's operations assistant, to one capability:\n"
    "- 'analytics': questions about business data/metrics (sales, revenue, products, "
    "customers, refunds, channels, time windows).\n"
    "- 'marketing': requests to CREATE or GENERATE a video ad / reel / creative for a product.\n"
    "- 'clarify': ambiguous, or neither of the above.\n\n"
    "For a marketing request that references a product (by name, or 'it'/'that one' pointing "
    "at a product discussed earlier), set product_hint to that product's name. Always give a "
    "one-line reason."
)


def _last_user_text(messages: list) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message.content if isinstance(message.content, str) else str(message.content)
    return ""


DASHBOARD_INSTRUCTIONS = (
    "Compose a compact operator dashboard from this analytics answer. Extract 1-4 headline stats "
    "as label + a pre-formatted value (e.g. value 'LKR 105,850', '73', '4.2%'). If the data is "
    "naturally tabular, add a small table (<= 6 rows) of stringified cells. If nothing is "
    "dashboard-worthy (a single trivial number, or a non-data answer), return empty stats and no "
    "table."
)


def _sql_results_from_messages(messages: list) -> str:
    """Collect the run_sql results from the agent's tool messages, for the dashboard's context.

    With the analytics agent running as a subgraph node, its run_sql calls and their ToolMessage
    results are now inline messages in the thread — pair each run_sql call to its result by id."""
    run_sql_ids = {
        tc.get("id")
        for m in messages
        for tc in (getattr(m, "tool_calls", None) or [])
        if tc.get("name") == "run_sql"
    }
    parts = []
    for m in messages:
        if getattr(m, "tool_call_id", None) in run_sql_ids:
            content = m.content
            parts.append(content if isinstance(content, str) else str(content))
    return "\n\n".join(parts)


def _build_dashboard(model, answer: str, query_results: str) -> AnalyticsDashboard | None:
    """Best-effort generative-UI dashboard from the final answer + the SQL the agent ran.

    Returns None (and the caller renders nothing) when generation fails or the answer isn't
    dashboard-worthy — generative UI is a nicety, never load-bearing for the text answer."""
    if not answer.strip():
        return None
    context = f"Answer:\n{answer}"
    if query_results:
        context += f"\n\nQuery results the answer is based on:\n{query_results[:2000]}"
    try:
        dashboard: AnalyticsDashboard = model.with_structured_output(AnalyticsDashboard).invoke(
            [SystemMessage(content=DASHBOARD_INSTRUCTIONS), HumanMessage(content=context)]
        )
    except Exception as exc:  # noqa: BLE001 — optional generative UI: never break the text answer
        log.info("dashboard.skipped", error=str(exc))
        return None
    if not dashboard.stats and dashboard.table is None:
        return None
    log.info("dashboard.built", stats=len(dashboard.stats), has_table=dashboard.table is not None)
    return dashboard


def build_orchestrator(
    *,
    settings: Settings | None = None,
    router_model=None,
    analytics_graph=None,
    marketing_graph=None,
    dashboard_model=None,
    checkpointer=None,
    store=None,
):
    """Compile the orchestrator. Subgraphs/router are injectable for offline tests; by default
    they're built from settings and share the orchestrator's `store` (so memory works) while
    relying on the orchestrator's `checkpointer` for HITL (passed via each node's config)."""
    settings = settings or get_settings()
    if router_model is None:
        # disable_streaming: the router classifies via with_structured_output — a forced tool call
        # whose parsed result is consumed into `route`, never appended to `messages`. With streaming
        # on, Aegra's `messages` stream still emits that internal call's token/tool-call
        # deltas (it captures every LLM call via callbacks), so the useStream UI would briefly render a phantom
        # partial message for a result that never lands. Disabling streaming keeps this internal call
        # off the token stream; it is never user-facing text, so nothing is lost. (The router,
        # dashboard, and marketing models all disable streaming for this reason; the analytics agent
        # keeps streaming on because its tokens ARE the user-facing answer.)
        router_model = init_chat_model(settings.router_model, temperature=0, disable_streaming=True)
    if analytics_graph is None:
        analytics_graph = build_analytics_graph(settings=settings, store=store)
    if marketing_graph is None:
        marketing_graph = build_marketing_graph(settings=settings, store=store, auto_approve=False)
    if dashboard_model is None:
        # Composes the generative-UI dashboard from an analytics answer — another
        # with_structured_output call whose result never lands in `messages`, so disable_streaming
        # for the same reason as the router (above). Construction needs a provider key; without one
        # (e.g. offline tests that don't inject a fake) we simply disable the dashboard — never the
        # text answer.
        try:
            dashboard_model = init_chat_model(settings.model, temperature=0, disable_streaming=True)
        except Exception:  # noqa: BLE001 — no key → dashboards off, the rest of the app still runs
            dashboard_model = None

    def route(state: OrchestratorState) -> Command[Literal["analytics", "marketing", "clarify"]]:
        classifier = router_model.with_structured_output(RouteDecision)
        decision: RouteDecision = classifier.invoke(
            [SystemMessage(content=ROUTER_INSTRUCTIONS), *state["messages"]]
        )
        log.info("route.decided", capability=decision.capability, reason=decision.reason)
        # Store the dump, not the model — graph state is JSON-native (see nora/state.py).
        return Command(goto=decision.capability, update={"route": decision.model_dump()})

    def analytics_dashboard(state: OrchestratorState) -> dict:
        # Runs right AFTER the analytics agent subgraph node. The agent's full tool loop — its
        # run_sql calls, their results, and the streamed final answer — has already flowed into the
        # top-level thread as inline messages (that's the streaming we want). Here we add the one
        # thing that isn't a chat message: the generative-UI dashboard, composed from the final
        # answer + the SQL results the agent saw, pushed via push_ui_message (the useStream UI
        # renders it via LoadExternalComponent). Best-effort — skips silently if generation fails
        # (no provider key offline) or nothing is dashboard-worthy; the answer is never blocked on it.
        if dashboard_model is None:
            return {}
        messages = state["messages"]
        final = messages[-1]
        answer = final.content if isinstance(final.content, str) else str(final.content)
        dashboard = _build_dashboard(dashboard_model, answer, _sql_results_from_messages(messages))
        if dashboard is None:
            return {}
        data = dashboard.model_dump()
        # Same id → add_messages updates the final message in place (no duplicate).
        final.additional_kwargs = {**(final.additional_kwargs or {}), "dashboard": data}
        push_ui_message("analytics_dashboard", data, message=final)
        return {"messages": [final]}

    def marketing(state: OrchestratorState, config) -> dict:
        route_decision = state.get("route")  # RouteDecision dict (JSON-native state)
        request = _last_user_text(state["messages"])
        product_hint = route_decision["product_hint"] if route_decision else None
        # If the subgraph interrupts (human_review), this bubbles up and pauses the orchestrator;
        # on resume the node re-runs and the subgraph continues from its checkpoint.
        result = marketing_graph.invoke(
            initial_marketing_state(request, product_hint), config
        )
        brief = result.get("brief")  # VideoBrief dict, or None if rejected at review
        if brief is None:  # rejected at review
            return {"messages": [AIMessage(content="Creative cancelled — no brief produced.")]}
        summary = (
            f"Video brief ready for {brief['product_name']}: \"{brief['concept']}\" — hook: "
            f"\"{brief['hook']}\". {len(brief['shots'])} shots, ~{brief['target_duration_s']:.0f}s, "
            f"CTA: {brief['cta']}. Render: {result.get('render_result', {}).get('status')}."
        )
        return {
            "messages": [AIMessage(content=summary, additional_kwargs={"video_brief": brief})]
        }

    def clarify(state: OrchestratorState) -> dict:
        return {
            "messages": [
                AIMessage(
                    content="I can answer a question about the business data, or create a video "
                    "ad for a product. Which would you like — and for which product?"
                )
            ]
        }

    builder = StateGraph(OrchestratorState, context_schema=Context)
    builder.add_node("route", route)
    # Analytics is added as a real subgraph NODE (not invoked imperatively): because it's part of
    # the graph, its messages — the run_sql tool-call steps AND the streamed final answer — flow
    # live into the top-level thread and render inline (clients opt in with `streamSubgraphs: true`).
    # `analytics_dashboard` runs right after to attach the generative-UI card from that answer.
    builder.add_node("analytics", analytics_graph)
    builder.add_node("analytics_dashboard", analytics_dashboard)
    # Marketing stays an imperative function node: its state is disjoint from the chat (it produces
    # a structured brief, not a token-streamed reply), and invoking the subgraph with `config` is
    # what lets a HITL interrupt() deep inside it bubble up and pause the whole orchestrator.
    builder.add_node("marketing", marketing)
    builder.add_node("clarify", clarify)
    builder.add_edge(START, "route")
    # route dispatches via Command(goto=...); analytics flows through its dashboard, then each ends.
    builder.add_edge("analytics", "analytics_dashboard")
    builder.add_edge("analytics_dashboard", END)
    builder.add_edge("marketing", END)
    builder.add_edge("clarify", END)

    return builder.compile(checkpointer=checkpointer, store=store)


def make_graph():
    """Factory for a platform server (Aegra via aegra.json).

    The platform provides persistence — the Postgres checkpointer (so HITL interrupts persist
    and resume) and the semantic Store (configured under `store.index` in aegra.json). So we
    compile WITHOUT our own: the platform injects them at runtime, and the store propagates into
    the analytics/marketing subgraphs. Seed the Store's brand voice + metric definitions once
    after the server is up with `apps/nora/scripts/seed_store.py`.

    (The CLI in `app.py` is the self-contained path — it builds and seeds its own in-memory
    checkpointer + Store.) Requires provider keys in the environment (it builds real models)."""
    return build_orchestrator(settings=get_settings())
