"""Tests for the orchestrator supervisor + the canonical end-to-end demo flow (M4).

All offline: a fake supervisor model (`ScriptedChatModel`) emits handoff tool-calls
(`to_analytics` / `to_marketing`) to delegate, the analytics/marketing subgraphs are driven by
scripted fakes, and the orchestrator ties them together on one thread_id — including the marketing
HITL pause bubbling up through the supervisor.

A single-capability turn scripts TWO supervisor responses: the handoff, then a closer the
supervisor pops when the capability returns to it (it ends silently because the capability already
answered inline).
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
from tests.fakes import ScriptedChatModel, ai_final, ai_tool_call
from tests.test_marketing_graph import _passing_model


def _dummy_analytics():
    return build_analytics_graph(model=ScriptedChatModel([ai_final("(unused)")]))


def _cfg(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _brief_from_ui(result) -> dict | None:
    """The marketing brief rides the generative-UI channel now (push_ui_message("video_brief",
    {"brief": ...})), not additional_kwargs — pull it back out of result["ui"]."""
    for ui in result.get("ui", []):
        if ui.get("name") == "video_brief":
            return ui["props"]["brief"]
    return None


def test_data_question_routes_to_analytics():
    orch = build_orchestrator(
        supervisor_model=ScriptedChatModel(
            [
                ai_tool_call("to_analytics", {"task": "what's our top product?"}, "h1"),
                ai_final(""),  # capability answered → supervisor ends silently
            ]
        ),
        analytics_graph=build_analytics_graph(
            model=ScriptedChatModel([ai_final("Top product: Ceylon Cinnamon (Alba).")])
        ),
        marketing_graph=build_marketing_graph(model=_passing_model(), auto_approve=True),
        checkpointer=InMemorySaver(),
    )
    result = orch.invoke({"messages": [HumanMessage("what's our top product?")]}, _cfg("a1"))
    # The supervisor ends silently after delegating, so the analytics answer is the last message.
    assert "Ceylon Cinnamon" in result["messages"][-1].content


def test_analytics_agent_surfaces_its_work_inline():
    """Subgraph-as-node wiring: the analytics agent is a real graph node, so its tool loop — the
    run_sql call AND its ToolMessage result — flows into top-level state as inline messages (that's
    what streams live in the UI with `streamSubgraphs`), ending with the final answer."""
    orch = build_orchestrator(
        supervisor_model=ScriptedChatModel(
            [ai_tool_call("to_analytics", {"task": "how many?"}, "h1"), ai_final("")]
        ),
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
    messages = result["messages"]

    # The agent's run_sql call and its ToolMessage result are inline (not hidden behind an
    # imperative .invoke()), so the UI can stream the agent's work step by step.
    assert any(isinstance(m, ToolMessage) for m in messages)
    assert any(
        tc["name"] == "run_sql"
        for m in messages
        for tc in (getattr(m, "tool_calls", None) or [])
    )
    # The turn still ends with the agent's final answer (supervisor ends silently after it).
    final = messages[-1]
    assert final.content == "There is exactly one."
    assert not getattr(final, "tool_calls", None)
    assert "tool_trace" not in (final.additional_kwargs or {})


def test_marketing_request_routes_and_carries_product_hint():
    orch = build_orchestrator(
        supervisor_model=ScriptedChatModel(
            [
                ai_tool_call(
                    "to_marketing",
                    {"task": "make a 30s reel", "product_hint": "Roasted Curry Powder"},
                    "h1",
                ),
                ai_final(""),
            ]
        ),
        analytics_graph=_dummy_analytics(),
        marketing_graph=build_marketing_graph(model=_passing_model(), auto_approve=True),
        checkpointer=InMemorySaver(),
    )
    result = orch.invoke({"messages": [HumanMessage("make a 30s reel for it")]}, _cfg("m1"))
    # product_hint flowed through the handoff into the marketing run and grounded the brief.
    brief = _brief_from_ui(result)
    assert "Roasted Curry Powder" in brief["product_name"]


class _MalformedMarketingGraph:
    """A marketing subgraph stand-in that returns a brief missing required keys — proves the
    orchestrator's marketing node degrades to text instead of KeyError-crashing the turn."""

    def invoke(self, state, config=None):  # noqa: ARG002 — ignores input by design
        return {"brief": {"concept": "Bold idea"}}  # no product_name/hook/shots/target_duration_s/cta


def test_marketing_malformed_brief_degrades_to_text():
    """A partial/malformed brief must degrade to a friendly reply (like workspace), not crash the
    turn on brief['product_name']. The marketing node guards its post-invoke formatting block."""
    orch = build_orchestrator(
        supervisor_model=ScriptedChatModel(
            [ai_tool_call("to_marketing", {"task": "make a reel"}, "h1"), ai_final("")]
        ),
        analytics_graph=_dummy_analytics(),
        marketing_graph=_MalformedMarketingGraph(),
        checkpointer=InMemorySaver(),
    )
    result = orch.invoke({"messages": [HumanMessage("make a reel")]}, _cfg("m-bad"))
    assert "couldn't assemble" in result["messages"][-1].content
    # No video_brief card was emitted for the malformed brief.
    assert not any(ui.get("name") == "video_brief" for ui in result.get("ui", []))


def test_ambiguous_request_asks_to_clarify():
    """No handoff tool-call → the supervisor's text reply IS the clarification (the old `clarify`
    node is gone; the supervisor absorbs it)."""
    orch = build_orchestrator(
        supervisor_model=ScriptedChatModel(
            [ai_final("I can answer a data question, or make a video ad. Which would you like?")]
        ),
        analytics_graph=_dummy_analytics(),
        marketing_graph=build_marketing_graph(model=_passing_model(), auto_approve=True),
        checkpointer=InMemorySaver(),
    )
    result = orch.invoke({"messages": [HumanMessage("hey there")]}, _cfg("c1"))
    assert "which would you like" in result["messages"][-1].content.lower()


def test_supervisor_failure_degrades_to_clarify():
    """A flaky supervisor (raises during the LLM call) shouldn't crash the turn — fall back to a
    clarifying reply. The empty-script fake raises on .invoke(), standing in for any failure."""
    orch = build_orchestrator(
        supervisor_model=ScriptedChatModel([]),  # no scripted responses → .invoke() raises
        analytics_graph=_dummy_analytics(),
        marketing_graph=build_marketing_graph(model=_passing_model(), auto_approve=True),
        checkpointer=InMemorySaver(),
    )
    result = orch.invoke({"messages": [HumanMessage("anything at all")]}, _cfg("r-fail"))
    assert "which would you like" in result["messages"][-1].content.lower()


def test_canonical_demo_flow_on_one_thread():
    """ask for the top product → answer → 'make a video ad for it' → pause for review → finish.

    The supervisor is invoked twice per turn (delegate, then a silent closer when the capability
    returns), so the script is [handoff, closer, handoff, closer] across the two turns."""
    orch = build_orchestrator(
        supervisor_model=ScriptedChatModel(
            [
                ai_tool_call("to_analytics", {"task": "best-selling product in Colombo?"}, "h1"),
                ai_final(""),
                ai_tool_call(
                    "to_marketing",
                    {"task": "make a video ad", "product_hint": "Ceylon Cinnamon (Alba)"},
                    "h2",
                ),
                ai_final(""),
            ]
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

    # Turn 2 — marketing delegates and pauses at human_review (interrupt bubbles up).
    r2 = orch.invoke({"messages": [HumanMessage("great, make a video ad for it")]}, cfg)
    assert "__interrupt__" in r2
    assert orch.get_state(cfg).interrupts

    # Resume the same thread — the workflow finishes and pushes the brief on the UI channel.
    r3 = orch.invoke(Command(resume={"approved": True}), cfg)
    brief = _brief_from_ui(r3)
    assert "Ceylon Cinnamon" in brief["product_name"]


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="requires a live LLM key")
def test_live_orchestrator_answers_a_data_question():
    from langchain_core.messages import AIMessage

    from nora.memory import build_store, seed_brand_knowledge

    store = build_store(__import__("nora.config", fromlist=["get_settings"]).get_settings())
    seed_brand_knowledge(store)
    orch = build_orchestrator(checkpointer=InMemorySaver(), store=store)
    result = orch.invoke(
        {"messages": [HumanMessage("How many products do we sell?")]}, _cfg("live")
    )
    # The supervisor either delegated to a capability (answer in the thread) or asked to clarify —
    # either way the turn ends with an AI message and doesn't crash.
    assert isinstance(result["messages"][-1], AIMessage)
    assert result["messages"][-1].content
