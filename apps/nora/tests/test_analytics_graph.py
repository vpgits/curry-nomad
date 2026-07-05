"""Tests for the analytics agent loop (M1).

The headline check (`test_self_correction_loop`) drives the whole loop offline with a scripted
model: a deliberately wrong-column query fails, the DB error returns as a ToolMessage, the
(scripted) model "repairs" the SQL, and the loop finishes with an answer. A live end-to-end
test runs only when an OPENAI_API_KEY is present.
"""

from __future__ import annotations

import os

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from nora.analytics.graph import build_analytics_graph, handle_sql_error, should_continue
from nora.analytics.tools import ANALYTICS_TOOLS
from nora.state import AnalyticsState
from tests.fakes import ScriptedChatModel, ai_final, ai_tool_call

# A wrong-column query (order_items has no `name`) → triggers self-correction.
_BAD_SQL = "SELECT name, SUM(quantity*unit_price_lkr) AS rev FROM order_items GROUP BY product_id ORDER BY rev DESC LIMIT 1"
_GOOD_SQL = (
    "SELECT p.name, SUM(oi.quantity*oi.unit_price_lkr) AS rev "
    "FROM order_items oi JOIN products p ON p.product_id=oi.product_id "
    "JOIN orders o ON o.order_id=oi.order_id WHERE o.status!='cancelled' "
    "GROUP BY p.product_id ORDER BY rev DESC LIMIT 1"
)


def test_should_continue_routes_to_tools_when_tool_calls_present():
    state = {"messages": [ai_tool_call("run_sql", {"query": "SELECT 1"}, "c1")]}
    assert should_continue(state) == "tools"


def test_should_continue_ends_when_no_tool_calls():
    state = {"messages": [AIMessage(content="done")]}
    assert should_continue(state) == END


def test_toolnode_converts_sqlerror_to_toolmessage():
    """A raised SqlError becomes a ToolMessage (the repair hint), not a crash.

    ToolNode needs the graph runtime, so we exercise it inside a one-node graph.
    """
    builder = StateGraph(AnalyticsState)
    builder.add_node("tools", ToolNode(ANALYTICS_TOOLS, handle_tool_errors=handle_sql_error))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile()

    result = graph.invoke(
        {"messages": [ai_tool_call("run_sql", {"query": "SELECT bogus FROM products"}, "c1")]}
    )
    msg = result["messages"][-1]
    assert isinstance(msg, ToolMessage)
    assert "failed" in msg.content.lower()
    assert "describe_table" in msg.content


def test_self_correction_loop():
    """End-to-end loop with a scripted model: bad SQL → error → repaired SQL → answer."""
    model = ScriptedChatModel(
        [
            ai_tool_call("run_sql", {"query": _BAD_SQL}, "c1"),  # fails
            ai_tool_call("run_sql", {"query": _GOOD_SQL}, "c2"),  # succeeds
            ai_final("The highest-revenue product is Ceylon Cinnamon (Alba)."),
        ]
    )
    graph = build_analytics_graph(model=model)
    result = graph.invoke({"messages": [HumanMessage(content="What's our top product?")]})

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 2
    # First tool result is the repair hint; second carries real data.
    assert "failed" in tool_messages[0].content.lower()
    assert "Ceylon Cinnamon" in tool_messages[1].content
    # Loop terminated with a plain answer.
    assert result["messages"][-1].content.startswith("The highest-revenue product")


def test_query_guard_forces_a_query_after_a_narration():
    """Headline fix for the trace bug: the model first NARRATES intent ("I'm going to check the sales
    data…") with no tool call; the query guard loops back once, and on the nudge the model actually
    calls run_sql — so the answer is grounded in a real query instead of an empty preamble."""
    model = ScriptedChatModel(
        [
            ai_final("I'm going to check the sales data and report the top product."),  # narrate, no tool
            ai_tool_call("run_sql", {"query": "SELECT name FROM products ORDER BY product_id LIMIT 1"}, "c1"),
            ai_final("Your top product is Ceylon Cinnamon (Alba)."),
        ]
    )
    graph = build_analytics_graph(model=model)
    result = graph.invoke({"messages": [HumanMessage(content="what's our best seller?")]})

    ran_query = [m for m in result["messages"] if isinstance(m, ToolMessage) and m.name == "run_sql"]
    assert ran_query, "the guard should have nudged the agent into actually querying"
    assert "Ceylon Cinnamon" in result["messages"][-1].content


def test_query_guard_hides_the_spurious_first_pass_refusal():
    """When the model spuriously REFUSES on its first pass ("I can't complete that request.") before
    querying, the guard rescues the turn — and the phantom refusal must NOT survive as a visible
    message above the real answer. It's dropped and replaced by an empty, `do-not-render-` placeholder
    (empty → the answer extractor skips it; the id → the web client hides it), while still counting
    toward the guard's single-retry bound."""
    refusal = "I'm sorry, but I can't complete that request."
    model = ScriptedChatModel(
        [
            ai_final(refusal),  # spurious first-pass refusal, no tool call
            ai_tool_call("run_sql", {"query": "SELECT name FROM products LIMIT 1"}, "c1"),
            ai_final("Your top product is Ceylon Cinnamon (Alba)."),
        ]
    )
    graph = build_analytics_graph(model=model)
    result = graph.invoke({"messages": [HumanMessage(content="what's our best seller?")]})

    # The real answer is delivered…
    assert "Ceylon Cinnamon" in result["messages"][-1].content
    # …and the refusal is gone from every VISIBLE message (mirrors the web client's do-not-render filter).
    visible = [m for m in result["messages"] if not str(getattr(m, "id", "") or "").startswith("do-not-render-")]
    assert not any(refusal in (getattr(m, "content", "") or "") for m in visible), (
        "the spurious refusal must not render above the answer"
    )


def test_query_guard_bounds_to_one_nudge_then_terminates():
    """The guard is bounded: a first tool-less reply is nudged ONCE; a second tool-less reply ends the
    loop (no infinite nudging) — so a stubborn or genuinely no-data answer still terminates."""
    model = ScriptedChatModel([ai_final("Let me look into that."), ai_final("42 orders.")])
    graph = build_analytics_graph(model=model)
    result = graph.invoke({"messages": [HumanMessage(content="how many orders?")]})
    assert result["messages"][-1].content == "42 orders."  # ended on the second answer
    assert not any(isinstance(m, ToolMessage) for m in result["messages"])  # never forced a fake query


def test_query_guard_does_not_fire_after_a_tool_ran():
    """No false nudge: a tool-less final answer that FOLLOWS real tool use is accepted as-is — the
    guard only catches the 'never touched the DB' case, so a normal tool→answer turn isn't retried."""
    model = ScriptedChatModel([ai_tool_call("list_tables", {}, "c1"), ai_final("We have 5 tables.")])
    graph = build_analytics_graph(model=model)
    result = graph.invoke({"messages": [HumanMessage(content="what tables exist?")]})
    assert result["messages"][-1].content == "We have 5 tables."  # not nudged — a tool ran this turn


def test_terminates_gracefully_at_step_budget():
    """A model that never stops calling tools must degrade to a plain answer when the step budget is
    nearly spent — NOT raise GraphRecursionError (which, since analytics runs as a subgraph node,
    would crash the whole turn). The `remaining_steps` guard in llm_node enforces this."""
    # Always asks for a harmless tool; without the guard this loops until GraphRecursionError.
    model = ScriptedChatModel([ai_tool_call("list_tables", {}, f"c{i}") for i in range(12)])
    graph = build_analytics_graph(model=model)
    result = graph.invoke(
        {"messages": [HumanMessage(content="loop forever")]},
        {"recursion_limit": 8},
    )
    final = result["messages"][-1]
    assert not getattr(final, "tool_calls", None)  # ended cleanly, not mid tool-call
    assert "within the available steps" in final.content


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="requires a live LLM key")
def test_live_agent_answers_a_data_question():
    graph = build_analytics_graph()
    result = graph.invoke(
        {"messages": [HumanMessage(content="How many products do we sell?")]}
    )
    final = result["messages"][-1]
    assert isinstance(final, AIMessage) and final.content
