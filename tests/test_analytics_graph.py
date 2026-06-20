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


def test_loop_terminates_on_direct_answer():
    """If the model answers without tools, the loop ends immediately."""
    model = ScriptedChatModel([ai_final("42 orders.")])
    graph = build_analytics_graph(model=model)
    result = graph.invoke({"messages": [HumanMessage(content="hi")]})
    assert result["messages"][-1].content == "42 orders."
    assert not any(isinstance(m, ToolMessage) for m in result["messages"])


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="requires a live LLM key")
def test_live_agent_answers_a_data_question():
    graph = build_analytics_graph()
    result = graph.invoke(
        {"messages": [HumanMessage(content="How many products do we sell?")]}
    )
    final = result["messages"][-1]
    assert isinstance(final, AIMessage) and final.content
