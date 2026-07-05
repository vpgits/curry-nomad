"""Tests for human-in-the-loop + memory (M3).

HITL: the marketing workflow pauses at `human_review`; resuming approves / edits / rejects.
The interrupt genuinely depends on a checkpointer + thread_id. Memory: a definition placed in
the Store is injected into the analytics prompt (offline, via a no-index store + a capturing
fake model). Behavior-shaping end-to-end (memory changes the answer; brand voice shapes the
post copy) needs a live model and is covered by the eval harness / skipped here.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from nora.analytics.graph import build_analytics_graph
from nora.marketing.graph import build_marketing_graph, initial_marketing_state
from nora.memory import GLOBAL_DEFINITIONS, seed_brand_knowledge
from nora.schemas import PostBrief
from tests.fakes import ScriptedChatModel, ai_final, ai_tool_call
from tests.test_marketing_graph import _passing_model

THREAD = {"configurable": {"thread_id": "hitl-1"}}


# --- HITL -----------------------------------------------------------------------------


def test_workflow_pauses_at_human_review():
    graph = build_marketing_graph(model=_passing_model(), checkpointer=InMemorySaver())
    result = graph.invoke(initial_marketing_state("Instagram post", "Cloves"), THREAD)
    assert "__interrupt__" in result
    state = graph.get_state(THREAD)
    assert state.interrupts  # pending HITL
    assert "brief" not in state.values  # paused before the expensive steps


def test_resume_approve_proceeds_to_brief():
    graph = build_marketing_graph(model=_passing_model(), checkpointer=InMemorySaver())
    graph.invoke(initial_marketing_state("Instagram post", "Cloves"), THREAD)
    result = graph.invoke(Command(resume={"approved": True}), THREAD)
    assert PostBrief(**result["brief"]).product_name  # state stores a dict; validate it
    assert result["render_result"]["status"] == "placeholder"


def test_resume_reject_routes_to_cancel():
    cfg = {"configurable": {"thread_id": "reject-1"}}
    graph = build_marketing_graph(model=_passing_model(), checkpointer=InMemorySaver())
    graph.invoke(initial_marketing_state("Instagram post", "Cloves"), cfg)
    result = graph.invoke(Command(resume={"approved": False}), cfg)
    assert result["render_result"]["status"] == "cancelled"
    assert "brief" not in result


def test_resume_with_edited_copy_is_honored():
    cfg = {"configurable": {"thread_id": "edit-1"}}
    graph = build_marketing_graph(model=_passing_model(), checkpointer=InMemorySaver())
    graph.invoke(initial_marketing_state("Instagram post", "Cloves"), cfg)
    edited = {
        "caption": "EDITED HOOK from the operator\nthe rest of the edited copy",
        "on_screen_texts": ["EDITED HOOK", "the rest"],
    }
    result = graph.invoke(Command(resume={"approved": True, "edited_copy": edited}), cfg)
    brief = PostBrief(**result["brief"])  # state stores a dict
    assert brief.caption.startswith("EDITED HOOK from the operator")


def test_auto_approve_skips_the_interrupt():
    # No checkpointer needed because no interrupt is raised.
    graph = build_marketing_graph(model=_passing_model(), auto_approve=True)
    result = graph.invoke(initial_marketing_state("Instagram post", "Cloves"))
    assert PostBrief(**result["brief"]).product_name


def test_interrupt_requires_a_checkpointer():
    graph = build_marketing_graph(model=_passing_model())  # no checkpointer
    graph.invoke(initial_marketing_state("Instagram post", "Cloves"))  # pauses ephemerally
    with pytest.raises(RuntimeError, match="checkpointer"):
        graph.invoke(Command(resume={"approved": True}))


def test_interrupt_requires_a_thread_id():
    graph = build_marketing_graph(model=_passing_model(), checkpointer=InMemorySaver())
    with pytest.raises(ValueError, match="thread_id"):
        graph.invoke(initial_marketing_state("Instagram post", "Cloves"))  # no config/thread_id


# --- Memory ---------------------------------------------------------------------------


def test_seed_brand_knowledge_populates_both_namespaces():
    store = InMemoryStore()
    seed_brand_knowledge(store)
    from nora.memory import GLOBAL_BRAND

    assert store.search(GLOBAL_BRAND, query="voice")
    assert store.search(GLOBAL_DEFINITIONS, query="revenue")


def test_analytics_injects_store_definitions_into_prompt():
    """A metric definition in the Store must reach the analytics system prompt (the wiring
    that lets memory shape the SQL). Verified offline via a no-index store + capturing model."""
    store = InMemoryStore()
    store.put(GLOBAL_DEFINITIONS, "revenue", {"text": "MAGIC_REVENUE_RULE net of refunds"})
    model = ScriptedChatModel([ai_tool_call("list_tables", {}, "c1"), ai_final("done")])  # engage DB (query guard)
    graph = build_analytics_graph(model=model, store=store)

    graph.invoke({"messages": [HumanMessage(content="What is total revenue?")]})

    system_text = " ".join(
        str(m.content) for m in model.last_messages if isinstance(m, SystemMessage)
    )
    assert "MAGIC_REVENUE_RULE" in system_text


def test_brand_voice_from_store_reaches_the_copy_prompt():
    """Brand voice placed in the Store must flow through load_brand into the post-copy prompt
    (the wiring behind 'brand voice visibly shapes the generated copy')."""
    store = InMemoryStore()
    from nora.memory import GLOBAL_BRAND

    store.put(GLOBAL_BRAND, "voice", {"text": "MAGIC_BRAND_VOICE cheeky and proud"})
    model = _passing_model()
    graph = build_marketing_graph(
        model=model, store=store, checkpointer=InMemorySaver(), auto_approve=True
    )
    graph.invoke(initial_marketing_state("Instagram post", "Cloves"), {"configurable": {"thread_id": "bv-1"}})
    assert any("MAGIC_BRAND_VOICE" in p for p in model.prompts)


def test_analytics_without_store_has_no_definitions_block():
    model = ScriptedChatModel([ai_tool_call("list_tables", {}, "c1"), ai_final("done")])  # engage DB (query guard)
    graph = build_analytics_graph(model=model)  # no store
    graph.invoke({"messages": [HumanMessage(content="How many orders?")]})
    system_text = " ".join(
        str(m.content) for m in model.last_messages if isinstance(m, SystemMessage)
    )
    assert "from memory" not in system_text  # the definitions block header is absent


# --- recall_block + memory-aware supervisor / workspace (the reusable retrieval) ------------


def test_recall_block_none_store_and_empty_store_return_blank():
    """No store (platform pre-injection / memory-less graph) and a seeded-but-empty store both
    collapse to "" — the caller appends only when truthy, so a graph with no memory is unchanged."""
    from nora.memory import recall_block

    assert recall_block(None, None, "anything") == ""
    assert recall_block(InMemoryStore(), None, "anything") == ""  # no hits → ""


def test_recall_block_formats_shared_and_per_user_tiers():
    """recall_block folds BOTH tiers into one labelled block: global (shared) knowledge and — when a
    verified identity is present — this operator's private saved context."""
    from nora.memory import recall_block, user_ns

    store = InMemoryStore()
    store.put(GLOBAL_DEFINITIONS, "revenue", {"text": "MAGIC_SHARED_DEF net of refunds"})

    class _AuthUser:  # mimics Aegra's server-injected user object (has `.identity`)
        identity = "operator-42"  # period-free (InMemoryStore rejects '.' in namespace labels)

    cfg = {"configurable": {"langgraph_auth_user": _AuthUser()}}
    store.put(user_ns("operator-42", "preferences"), "cur", {"text": "MAGIC_USER_PREF USD"})

    block = recall_block(store, cfg, "revenue and currency")
    assert "MAGIC_SHARED_DEF" in block
    assert "MAGIC_USER_PREF" in block
    assert "Shared knowledge" in block and "This operator" in block


def _mem_orchestrator(supervisor_model, store=None):
    """Build an orchestrator whose only live model is the scripted supervisor (analytics/marketing are
    inert), optionally with a seeded store — so a test can inspect the supervisor's captured prompt."""
    from nora.orchestrator import build_orchestrator

    return build_orchestrator(
        supervisor_model=supervisor_model,
        analytics_graph=build_analytics_graph(model=ScriptedChatModel([ai_final("(unused)")])),
        marketing_graph=build_marketing_graph(model=_passing_model(), auto_approve=True),
        checkpointer=InMemorySaver(),
        store=store,
    )


def test_supervisor_folds_memory_into_its_prompt():
    """The supervisor is memory-aware: seeded global knowledge reaches its system prompt, so both its
    routing and its direct clarifying replies can reflect long-term memory."""
    store = InMemoryStore()
    store.put(GLOBAL_DEFINITIONS, "revenue", {"text": "MAGIC_SUPERVISOR_MEM net of refunds"})
    supervisor_model = ScriptedChatModel([ai_final("Which product would you like?")])  # direct reply, no handoff
    orch = _mem_orchestrator(supervisor_model, store=store)
    orch.invoke({"messages": [HumanMessage("hello")]}, {"configurable": {"thread_id": "mem-sup-1"}})
    system_text = " ".join(
        str(m.content) for m in supervisor_model.last_messages if isinstance(m, SystemMessage)
    )
    assert "MAGIC_SUPERVISOR_MEM" in system_text


def test_supervisor_without_store_leaves_prompt_clean():
    """No store → no memory block appended (the supervisor prompt is exactly the base instructions),
    so scripted-model routing tests are unperturbed."""
    supervisor_model = ScriptedChatModel([ai_final("Which product would you like?")])
    orch = _mem_orchestrator(supervisor_model)  # no store
    orch.invoke({"messages": [HumanMessage("hello")]}, {"configurable": {"thread_id": "mem-sup-2"}})
    system_text = " ".join(
        str(m.content) for m in supervisor_model.last_messages if isinstance(m, SystemMessage)
    )
    assert "Relevant long-term memory" not in system_text


def test_workspace_agent_folds_memory_into_its_prompt():
    """The workspace agent's system prompt carries recalled memory when the orchestrator passes
    `memory_context` — so the operator's saved Google preferences shape its actions."""
    import asyncio

    from nora.workspace.graph import build_workspace_agent

    model = ScriptedChatModel([ai_final("Nothing to do.")])  # ends immediately; no tools needed
    agent = build_workspace_agent(model=model, tools_provider=lambda *, access_token: [], hitl="off")
    asyncio.run(
        agent([HumanMessage("check my sheets")], access_token="tok", memory_context="MAGIC_WS_MEM")
    )
    system_text = " ".join(
        str(m.content) for m in model.last_messages if isinstance(m, SystemMessage)
    )
    assert "MAGIC_WS_MEM" in system_text


# --- capability descriptions derive from the granted scopes (no more Gmail/Calendar-only drift) -----


def test_workspace_scope_summary_reflects_granted_scopes():
    """The scope summary is derived from `workspace_permissions`: it names the granted apps
    (Sheets/Docs/Drive/Tasks/Gmail) and does NOT invent an ungranted one (Calendar)."""
    from nora.config import Settings

    s = Settings(workspace_permissions="gmail:send sheets:full docs:full tasks:full drive:readonly")
    summary = s.workspace_scope_summary()
    for expected in ("Gmail", "Google Sheets", "Google Docs", "Google Tasks", "Google Drive"):
        assert expected in summary
    assert "Calendar" not in summary  # not granted → not advertised

    # Adding a scope widens the summary automatically (single source of truth).
    assert "Google Calendar" in Settings(
        workspace_permissions="gmail:send calendar:full"
    ).workspace_scope_summary()


def test_supervisor_prompt_advertises_workspace_write_scope():
    """The router's system prompt now tells it workspace can touch Sheets (not just email), and
    carries the delegation-bias rule — so it won't self-refuse a spreadsheet request."""
    supervisor_model = ScriptedChatModel([ai_final("ok")])
    orch = _mem_orchestrator(supervisor_model)  # default settings → sheets:full granted
    orch.invoke({"messages": [HumanMessage("hi")]}, {"configurable": {"thread_id": "scope-sup-1"}})
    system_text = " ".join(
        str(m.content) for m in supervisor_model.last_messages if isinstance(m, SystemMessage)
    )
    assert "Google Sheets" in system_text
    # the anti-self-refusal rule reached the prompt
    assert "decide yourself that a Google action is unsupported" in system_text


def test_workspace_agent_prompt_advertises_full_scope():
    """The workspace agent's own system prompt spells out its real reach (Sheets + Drive), derived
    from the granted scopes rather than the old 'email/calendar' blurb."""
    import asyncio

    from nora.workspace.graph import build_workspace_agent

    model = ScriptedChatModel([ai_final("done")])
    agent = build_workspace_agent(model=model, tools_provider=lambda *, access_token: [], hitl="off")
    asyncio.run(agent([HumanMessage("hi")], access_token="tok"))
    system_text = " ".join(
        str(m.content) for m in model.last_messages if isinstance(m, SystemMessage)
    )
    assert "Google Sheets" in system_text and "Drive" in system_text


def test_self_correcting_wrapper_handles_content_and_artifact_tool():
    """A wrapped MCP-style content_and_artifact tool must EXECUTE and return its content — not raise
    ValueError('a two-tuple ... is expected') from a response_format mismatch. That bug made an
    APPROVED create_spreadsheet fail on the middleware HITL path and get mislabeled as an approval
    mismatch."""
    import asyncio

    from langchain_core.tools import StructuredTool, ToolException

    from nora.workspace.graph import _self_correcting

    async def _ok(x: int):  # a content_and_artifact tool returns a (content, artifact) 2-tuple
        return ([{"type": "text", "text": f"made spreadsheet {x}"}], {"raw": x})

    wrapped = _self_correcting(
        StructuredTool.from_function(
            coroutine=_ok, name="create_spreadsheet", description="d",
            response_format="content_and_artifact",
        )
    )
    result = asyncio.run(wrapped.ainvoke({"x": 7}))  # must not raise
    assert "made spreadsheet 7" in str(result)

    async def _boom(x: int):
        raise ToolException("bad sheet id")

    bwrapped = _self_correcting(
        StructuredTool.from_function(
            coroutine=_boom, name="update_spreadsheet", description="d",
            response_format="content_and_artifact",
        )
    )
    # A recoverable ToolException becomes the curated self-correction string (still no ValueError).
    assert isinstance(asyncio.run(bwrapped.ainvoke({"x": 1})), str)
