"""Tests for human-in-the-loop + memory (M3).

HITL: the marketing workflow pauses at `human_review`; resuming approves / edits / rejects.
The interrupt genuinely depends on a checkpointer + thread_id. Memory: a definition placed in
the Store is injected into the analytics prompt (offline, via a no-index store + a capturing
fake model). Behavior-shaping end-to-end (memory changes the answer; brand voice shapes the
script) needs a live model and is covered by the eval harness / skipped here.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from nora.analytics.graph import build_analytics_graph
from nora.marketing.graph import build_marketing_graph, initial_marketing_state
from nora.memory import DEFINITIONS, seed_brand_knowledge
from nora.schemas import VideoBrief
from tests.fakes import ScriptedChatModel, ai_final, ai_tool_call
from tests.test_marketing_graph import _passing_model

THREAD = {"configurable": {"thread_id": "hitl-1"}}


# --- HITL -----------------------------------------------------------------------------


def test_workflow_pauses_at_human_review():
    graph = build_marketing_graph(model=_passing_model(), checkpointer=InMemorySaver())
    result = graph.invoke(initial_marketing_state("reel", "Cloves"), THREAD)
    assert "__interrupt__" in result
    state = graph.get_state(THREAD)
    assert state.interrupts  # pending HITL
    assert "brief" not in state.values  # paused before the expensive steps


def test_resume_approve_proceeds_to_brief():
    graph = build_marketing_graph(model=_passing_model(), checkpointer=InMemorySaver())
    graph.invoke(initial_marketing_state("reel", "Cloves"), THREAD)
    result = graph.invoke(Command(resume={"approved": True}), THREAD)
    assert VideoBrief(**result["brief"]).product_name  # state stores a dict; validate it
    assert result["render_result"]["status"] == "placeholder"


def test_resume_reject_routes_to_cancel():
    cfg = {"configurable": {"thread_id": "reject-1"}}
    graph = build_marketing_graph(model=_passing_model(), checkpointer=InMemorySaver())
    graph.invoke(initial_marketing_state("reel", "Cloves"), cfg)
    result = graph.invoke(Command(resume={"approved": False}), cfg)
    assert result["render_result"]["status"] == "cancelled"
    assert "brief" not in result


def test_resume_with_edited_script_is_honored():
    cfg = {"configurable": {"thread_id": "edit-1"}}
    graph = build_marketing_graph(model=_passing_model(), checkpointer=InMemorySaver())
    graph.invoke(initial_marketing_state("reel", "Cloves"), cfg)
    edited = [
        {"t_start_s": 0, "t_end_s": 3, "voiceover": "EDITED HOOK from the operator", "on_screen_text": None},
        {"t_start_s": 3, "t_end_s": 30, "voiceover": "the rest of the edited script", "on_screen_text": None},
    ]
    result = graph.invoke(Command(resume={"approved": True, "edited_script": edited}), cfg)
    brief = VideoBrief(**result["brief"])  # state stores a dict
    assert brief.script_beats[0].voiceover == "EDITED HOOK from the operator"


def test_auto_approve_skips_the_interrupt():
    # No checkpointer needed because no interrupt is raised.
    graph = build_marketing_graph(model=_passing_model(), auto_approve=True)
    result = graph.invoke(initial_marketing_state("reel", "Cloves"))
    assert VideoBrief(**result["brief"]).product_name


def test_interrupt_requires_a_checkpointer():
    graph = build_marketing_graph(model=_passing_model())  # no checkpointer
    graph.invoke(initial_marketing_state("reel", "Cloves"))  # pauses ephemerally
    with pytest.raises(RuntimeError, match="checkpointer"):
        graph.invoke(Command(resume={"approved": True}))


def test_interrupt_requires_a_thread_id():
    graph = build_marketing_graph(model=_passing_model(), checkpointer=InMemorySaver())
    with pytest.raises(ValueError, match="thread_id"):
        graph.invoke(initial_marketing_state("reel", "Cloves"))  # no config/thread_id


# --- Memory ---------------------------------------------------------------------------


def test_seed_brand_knowledge_populates_both_namespaces():
    store = InMemoryStore()
    seed_brand_knowledge(store)
    from nora.memory import BRAND

    assert store.search(BRAND, query="voice")
    assert store.search(DEFINITIONS, query="revenue")


def test_analytics_injects_store_definitions_into_prompt():
    """A metric definition in the Store must reach the analytics system prompt (the wiring
    that lets memory shape the SQL). Verified offline via a no-index store + capturing model."""
    store = InMemoryStore()
    store.put(DEFINITIONS, "revenue", {"text": "MAGIC_REVENUE_RULE net of refunds"})
    model = ScriptedChatModel([ai_tool_call("list_tables", {}, "c1"), ai_final("done")])  # engage DB (query guard)
    graph = build_analytics_graph(model=model, store=store)

    graph.invoke({"messages": [HumanMessage(content="What is total revenue?")]})

    system_text = " ".join(
        str(m.content) for m in model.last_messages if isinstance(m, SystemMessage)
    )
    assert "MAGIC_REVENUE_RULE" in system_text


def test_brand_voice_from_store_reaches_the_script_prompt():
    """Brand voice placed in the Store must flow through load_brand into the script prompt
    (the wiring behind 'brand voice visibly shapes the generated script')."""
    store = InMemoryStore()
    store.put(("curry_nomad", "brand"), "voice", {"text": "MAGIC_BRAND_VOICE cheeky and proud"})
    model = _passing_model()
    graph = build_marketing_graph(
        model=model, store=store, checkpointer=InMemorySaver(), auto_approve=True
    )
    graph.invoke(initial_marketing_state("reel", "Cloves"), {"configurable": {"thread_id": "bv-1"}})
    assert any("MAGIC_BRAND_VOICE" in p for p in model.prompts)


def test_analytics_without_store_has_no_definitions_block():
    model = ScriptedChatModel([ai_tool_call("list_tables", {}, "c1"), ai_final("done")])  # engage DB (query guard)
    graph = build_analytics_graph(model=model)  # no store
    graph.invoke({"messages": [HumanMessage(content="How many orders?")]})
    system_text = " ".join(
        str(m.content) for m in model.last_messages if isinstance(m, SystemMessage)
    )
    assert "from memory" not in system_text  # the definitions block header is absent
