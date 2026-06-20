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
from langgraph.types import Command

from nora.analytics.graph import build_analytics_graph
from nora.config import Settings, get_settings
from nora.marketing.graph import build_marketing_graph, initial_marketing_state
from nora.observability import get_logger
from nora.schemas import Context, RouteDecision
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


def build_orchestrator(
    *,
    settings: Settings | None = None,
    router_model=None,
    analytics_graph=None,
    marketing_graph=None,
    checkpointer=None,
    store=None,
):
    """Compile the orchestrator. Subgraphs/router are injectable for offline tests; by default
    they're built from settings and share the orchestrator's `store` (so memory works) while
    relying on the orchestrator's `checkpointer` for HITL (passed via each node's config)."""
    settings = settings or get_settings()
    if router_model is None:
        router_model = init_chat_model(settings.router_model, temperature=0)
    if analytics_graph is None:
        analytics_graph = build_analytics_graph(settings=settings, store=store)
    if marketing_graph is None:
        marketing_graph = build_marketing_graph(settings=settings, store=store, auto_approve=False)

    def route(state: OrchestratorState) -> Command[Literal["analytics", "marketing", "clarify"]]:
        classifier = router_model.with_structured_output(RouteDecision)
        decision: RouteDecision = classifier.invoke(
            [SystemMessage(content=ROUTER_INSTRUCTIONS), *state["messages"]]
        )
        log.info("route.decided", capability=decision.capability, reason=decision.reason)
        return Command(goto=decision.capability, update={"route": decision})

    def analytics(state: OrchestratorState, config) -> dict:
        # Invoke the analytics subgraph with the running conversation; surface its final answer.
        result = analytics_graph.invoke({"messages": state["messages"]}, config)
        return {"messages": [result["messages"][-1]]}

    def marketing(state: OrchestratorState, config) -> dict:
        route_decision = state.get("route")
        request = _last_user_text(state["messages"])
        product_hint = route_decision.product_hint if route_decision else None
        # If the subgraph interrupts (human_review), this bubbles up and pauses the orchestrator;
        # on resume the node re-runs and the subgraph continues from its checkpoint.
        result = marketing_graph.invoke(
            initial_marketing_state(request, product_hint), config
        )
        brief = result.get("brief")
        if brief is None:  # rejected at review
            return {"messages": [AIMessage(content="Creative cancelled — no brief produced.")]}
        summary = (
            f"Video brief ready for {brief.product_name}: \"{brief.concept}\" — hook: "
            f"\"{brief.hook}\". {len(brief.shots)} shots, ~{brief.target_duration_s:.0f}s, "
            f"CTA: {brief.cta}. Render: {result.get('render_result', {}).get('status')}."
        )
        return {
            "messages": [AIMessage(content=summary, additional_kwargs={"video_brief": brief.model_dump()})]
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
    builder.add_node("analytics", analytics)
    builder.add_node("marketing", marketing)
    builder.add_node("clarify", clarify)
    builder.add_edge(START, "route")
    # route dispatches via Command(goto=...); each capability ends the turn.
    builder.add_edge("analytics", END)
    builder.add_edge("marketing", END)
    builder.add_edge("clarify", END)

    return builder.compile(checkpointer=checkpointer, store=store)


def make_graph():
    """Factory for a platform server (Aegra via aegra.json, or `langgraph dev`).

    The platform provides persistence — the Postgres checkpointer (so HITL interrupts persist
    and resume) and the semantic Store (configured under `store.index` in aegra.json). So we
    compile WITHOUT our own: the platform injects them at runtime, and the store propagates into
    the analytics/marketing subgraphs. Seed the Store's brand voice + metric definitions once
    after the server is up with `apps/nora/scripts/seed_store.py`.

    (The CLI in `app.py` is the self-contained path — it builds and seeds its own in-memory
    checkpointer + Store.) Requires provider keys in the environment (it builds real models)."""
    return build_orchestrator(settings=get_settings())
