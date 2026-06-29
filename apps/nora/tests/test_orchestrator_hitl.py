"""Orchestrator-level HITL + checkpoint-serialization coverage.

The other HITL tests drive the marketing subgraph *standalone*. These drive the canonical
platform path: the orchestrator invokes the marketing subgraph imperatively
(`marketing_graph.invoke(state, config)`) with the checkpointer on the *orchestrator* and
propagated via `config`. An interrupt deep in the subgraph must bubble up and pause the whole
orchestrator, and `Command(resume=...)` on the same thread must flow back down.

The strict-serializer variant guards the JSON-native-state design (nora/state.py): under a
checkpointer whose serializer only deserializes allow-listed modules — i.e.
`LANGGRAPH_STRICT_MSGPACK=true`, slated to become the LangGraph default — custom Pydantic types
in state would round-trip as bare dicts and break attribute access on resume. Storing dicts
dodges that. This test fails if anyone reintroduces Pydantic objects into graph state.
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import Command

from nora.marketing.graph import build_marketing_graph
from nora.memory import build_checkpointer
from nora.orchestrator import build_orchestrator
from tests.fakes import ScriptedChatModel, ai_final, ai_tool_call
from tests.test_marketing_graph import _passing_model


class _StubAnalytics:
    """Never invoked on the marketing path. Callable so it's a valid graph node (the analytics
    subgraph is now added via `add_node`), but it raises if the marketing path ever reaches it."""

    def __call__(self, *args, **kwargs):  # noqa: ARG002
        raise AssertionError("analytics subgraph should not run for a marketing request")


def _orchestrator(checkpointer):
    return build_orchestrator(
        # The supervisor delegates to marketing for Cloves, then ends silently when it returns.
        supervisor_model=ScriptedChatModel(
            [
                ai_tool_call(
                    "to_marketing",
                    {"task": "make a video ad for Cloves", "product_hint": "Cloves"},
                    "h1",
                ),
                ai_final(""),
            ]
        ),
        analytics_graph=_StubAnalytics(),
        marketing_graph=build_marketing_graph(model=_passing_model(), auto_approve=False),
        checkpointer=checkpointer,
        store=None,
    )


def _brief_from_ui(result) -> dict | None:
    """The marketing brief now rides the generative-UI channel (push_ui_message("video_brief",
    {"brief": ...})), not additional_kwargs. Pull it back out of result["ui"]."""
    for ui in result.get("ui", []):
        if ui.get("name") == "video_brief":
            return ui["props"]["brief"]
    return None


def _drive_pause_then_resume(checkpointer, thread_id: str, resume=None) -> dict:
    """Run the canonical demo: marketing request → pause at human_review → resume.

    Returns the full orchestrator result (so callers can read both the final message and the
    pushed UI cards). `resume` defaults to the structured dict a useStream `Command(resume=...)`
    sends. Pass a JSON *string* to exercise the CopilotKit transport, whose `useLangGraphInterrupt`
    resolves with a string (see `human_review`'s normalization guard in marketing/nodes.py)."""
    if resume is None:
        resume = {"approved": True}
    graph = _orchestrator(checkpointer)
    config = {"configurable": {"thread_id": thread_id}}

    graph.invoke({"messages": [HumanMessage(content="make a video ad for Cloves")]}, config)
    state = graph.get_state(config)
    assert state.interrupts, "interrupt from the marketing subgraph must surface on the orchestrator"
    assert state.next == ("marketing",), "the orchestrator pauses with the marketing node pending"

    result = graph.invoke(Command(resume=resume), config)
    assert not graph.get_state(config).interrupts, "resume must clear the interrupt, not re-pause"
    return result


def test_orchestrator_pauses_and_resumes_across_subgraph():
    result = _drive_pause_then_resume(build_checkpointer(), "orch-hitl-1")
    assert "Video brief ready" in result["messages"][-1].content
    brief = _brief_from_ui(result)
    assert isinstance(brief, dict) and brief["product_name"]  # JSON-native, ready for the UI


def test_orchestrator_resume_accepts_copilotkit_json_string_approve():
    """CopilotKit's `useLangGraphInterrupt` resolves with a *string*, not a dict. An approve sent
    as `Command(resume='{"approved": true}')` must parse back to a dict and proceed to the brief —
    the same outcome as the useStream dict path."""
    result = _drive_pause_then_resume(
        build_checkpointer(), "orch-hitl-ck-approve", resume=json.dumps({"approved": True})
    )
    assert "Video brief ready" in result["messages"][-1].content


def test_orchestrator_resume_accepts_copilotkit_json_string_reject():
    """The guard's load-bearing case: a *reject* sent as the string `'{"approved": false}'`. Without
    json.loads normalization the node would fall back to `bool(decision)`, and a non-empty string is
    truthy — silently approving a rejection. With the guard it must cancel."""
    result = _drive_pause_then_resume(
        build_checkpointer(), "orch-hitl-ck-reject", resume=json.dumps({"approved": False})
    )
    assert "cancelled" in result["messages"][-1].content.lower()


def test_orchestrator_resume_survives_strict_msgpack():
    """Same flow, but the checkpointer's serializer allow-lists nothing (strict mode). The
    interrupt state must still deserialize and the run must finish — proving no custom Pydantic
    type is persisted in graph state."""
    strict = InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=None))
    result = _drive_pause_then_resume(strict, "orch-hitl-strict-1")
    assert "Video brief ready" in result["messages"][-1].content
    assert _brief_from_ui(result)["product_name"]
