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

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import Command

from nora.marketing.graph import build_marketing_graph
from nora.memory import build_checkpointer
from nora.orchestrator import build_orchestrator
from nora.schemas import RouteDecision
from tests.test_marketing_graph import _passing_model


class _FakeRouter:
    """Always routes to marketing (avoids a real router model)."""

    def with_structured_output(self, schema, **kwargs):  # noqa: ARG002
        return self

    def invoke(self, messages, **kwargs):  # noqa: ARG002
        return RouteDecision(capability="marketing", reason="test", product_hint="Cloves")


class _StubAnalytics:
    """Never invoked on the marketing path."""

    def invoke(self, *args, **kwargs):  # noqa: ARG002
        raise AssertionError("analytics subgraph should not run for a marketing request")


def _orchestrator(checkpointer):
    return build_orchestrator(
        router_model=_FakeRouter(),
        analytics_graph=_StubAnalytics(),
        marketing_graph=build_marketing_graph(model=_passing_model(), auto_approve=False),
        checkpointer=checkpointer,
        store=None,
    )


def _drive_pause_then_resume(checkpointer, thread_id: str) -> AIMessage:
    """Run the canonical demo: marketing request → pause at human_review → resume(approve)."""
    graph = _orchestrator(checkpointer)
    config = {"configurable": {"thread_id": thread_id}}

    graph.invoke({"messages": [HumanMessage(content="make a video ad for Cloves")]}, config)
    state = graph.get_state(config)
    assert state.interrupts, "interrupt from the marketing subgraph must surface on the orchestrator"
    assert state.next == ("marketing",), "the orchestrator pauses with the marketing node pending"

    result = graph.invoke(Command(resume={"approved": True}), config)
    assert not graph.get_state(config).interrupts, "resume must clear the interrupt, not re-pause"
    return result["messages"][-1]


def test_orchestrator_pauses_and_resumes_across_subgraph():
    final = _drive_pause_then_resume(build_checkpointer(), "orch-hitl-1")
    assert "Video brief ready" in final.content
    brief = final.additional_kwargs["video_brief"]
    assert isinstance(brief, dict) and brief["product_name"]  # JSON-native, ready for the UI


def test_orchestrator_resume_survives_strict_msgpack():
    """Same flow, but the checkpointer's serializer allow-lists nothing (strict mode). The
    interrupt state must still deserialize and the run must finish — proving no custom Pydantic
    type is persisted in graph state."""
    strict = InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=None))
    final = _drive_pause_then_resume(strict, "orch-hitl-strict-1")
    assert "Video brief ready" in final.content
    assert final.additional_kwargs["video_brief"]["product_name"]
