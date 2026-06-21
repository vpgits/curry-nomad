"""Tests for the orchestrator routing + the canonical end-to-end demo flow (M4).

All offline: a fake router model returns scripted RouteDecisions, the analytics/marketing
subgraphs are driven by scripted fakes, and the orchestrator ties them together on one
thread_id — including the marketing HITL pause bubbling up through the orchestrator.
"""

from __future__ import annotations

import os

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from nora.analytics.graph import build_analytics_graph
from nora.marketing.graph import build_marketing_graph
from nora.orchestrator import build_orchestrator
from nora.schemas import RouteDecision
from tests.fakes import ScriptedChatModel, ScriptedStructuredModel, ai_final, ai_tool_call
from tests.test_marketing_graph import _passing_model


def _router(*decisions: RouteDecision) -> ScriptedStructuredModel:
    return ScriptedStructuredModel({RouteDecision: list(decisions)})


def _dummy_analytics():
    return build_analytics_graph(model=ScriptedChatModel([ai_final("(unused)")]))


def _cfg(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def test_data_question_routes_to_analytics():
    orch = build_orchestrator(
        router_model=_router(RouteDecision(capability="analytics", reason="data question")),
        analytics_graph=build_analytics_graph(
            model=ScriptedChatModel([ai_final("Top product: Ceylon Cinnamon (Alba).")])
        ),
        marketing_graph=build_marketing_graph(model=_passing_model(), auto_approve=True),
        checkpointer=InMemorySaver(),
    )
    result = orch.invoke({"messages": [HumanMessage("what's our top product?")]}, _cfg("a1"))
    assert result["route"]["capability"] == "analytics"
    assert "Ceylon Cinnamon" in result["messages"][-1].content


def test_analytics_subgraph_streams_into_top_level_state_and_post_builds_trace():
    """Native-subgraph wiring: the analytics agent is a real subgraph node, so its tool-loop
    messages flow into the orchestrator's `messages` channel (what CopilotKit streams live), and
    `analytics_post` distils this turn's calls into `tool_trace` on the final answer."""
    orch = build_orchestrator(
        router_model=_router(RouteDecision(capability="analytics", reason="data question")),
        analytics_graph=build_analytics_graph(
            model=ScriptedChatModel(
                [
                    ai_tool_call("run_sql", {"query": "SELECT 1 AS x"}, "c1"),
                    ai_final("There is exactly one."),
                ]
            )
        ),
        marketing_graph=build_marketing_graph(model=_passing_model(), auto_approve=True),
        checkpointer=InMemorySaver(),
    )
    result = orch.invoke({"messages": [HumanMessage("how many?")]}, _cfg("an-trace"))

    # The subgraph's intermediate tool call + its result now persist in top-level state (not
    # hidden behind an imperative .invoke()) — this is what lets the adapter stream them.
    assert any(isinstance(m, ToolMessage) for m in result["messages"])
    assert any(getattr(m, "tool_calls", None) for m in result["messages"])
    # analytics_post enriched the final answer with the scoped trace.
    final = result["messages"][-1]
    assert final.content == "There is exactly one."
    trace = final.additional_kwargs["tool_trace"]
    assert trace[0]["calls"][0]["name"] == "run_sql"


def test_marketing_request_routes_and_carries_product_hint():
    orch = build_orchestrator(
        router_model=_router(
            RouteDecision(capability="marketing", reason="make ad", product_hint="Roasted Curry Powder")
        ),
        analytics_graph=_dummy_analytics(),
        marketing_graph=build_marketing_graph(model=_passing_model(), auto_approve=True),
        checkpointer=InMemorySaver(),
    )
    result = orch.invoke({"messages": [HumanMessage("make a 30s reel for it")]}, _cfg("m1"))
    assert result["route"]["capability"] == "marketing"
    # product_hint flowed into the marketing run and grounded the brief in that product.
    brief = result["messages"][-1].additional_kwargs["video_brief"]
    assert "Roasted Curry Powder" in brief["product_name"]


def test_ambiguous_request_routes_to_clarify():
    orch = build_orchestrator(
        router_model=_router(RouteDecision(capability="clarify", reason="ambiguous")),
        analytics_graph=_dummy_analytics(),
        marketing_graph=build_marketing_graph(model=_passing_model(), auto_approve=True),
        checkpointer=InMemorySaver(),
    )
    result = orch.invoke({"messages": [HumanMessage("hey there")]}, _cfg("c1"))
    assert result["route"]["capability"] == "clarify"
    assert "which would you like" in result["messages"][-1].content.lower()


def test_canonical_demo_flow_on_one_thread():
    """ask for the top product → answer → 'make a video ad for it' → pause for review → finish."""
    orch = build_orchestrator(
        router_model=_router(
            RouteDecision(capability="analytics", reason="data question"),
            RouteDecision(capability="marketing", reason="make ad", product_hint="Ceylon Cinnamon (Alba)"),
        ),
        analytics_graph=build_analytics_graph(
            model=ScriptedChatModel([ai_final("Our best seller in Colombo is Ceylon Cinnamon (Alba).")])
        ),
        marketing_graph=build_marketing_graph(model=_passing_model(), auto_approve=False),
        checkpointer=InMemorySaver(),
    )
    cfg = _cfg("demo")

    # Turn 1 — analytics answers.
    r1 = orch.invoke({"messages": [HumanMessage("best-selling product in Colombo?")]}, cfg)
    assert "Ceylon Cinnamon" in r1["messages"][-1].content

    # Turn 2 — marketing routes and pauses at human_review (interrupt bubbles up).
    r2 = orch.invoke({"messages": [HumanMessage("great, make a video ad for it")]}, cfg)
    assert "__interrupt__" in r2
    assert orch.get_state(cfg).interrupts

    # Resume the same thread — the workflow finishes and returns the brief.
    r3 = orch.invoke(Command(resume={"approved": True}), cfg)
    brief = r3["messages"][-1].additional_kwargs["video_brief"]
    assert "Ceylon Cinnamon" in brief["product_name"]


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="requires a live LLM key")
def test_live_orchestrator_routes_a_data_question():
    from nora.memory import build_store, seed_brand_knowledge

    store = build_store(__import__("nora.config", fromlist=["get_settings"]).get_settings())
    seed_brand_knowledge(store)
    orch = build_orchestrator(checkpointer=InMemorySaver(), store=store)
    result = orch.invoke(
        {"messages": [HumanMessage("How many products do we sell?")]}, _cfg("live")
    )
    assert result["route"]["capability"] in {"analytics", "marketing", "clarify"}
