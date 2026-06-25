"""Offline tests for the `workspace` capability (the Google Workspace MCP agent).

Same scripted-fake approach as the other suites — no provider key, no MCP server, no network:
- a `ScriptedChatModel` drives the agent loop (tool call → final answer), and
- a fake `tools_provider` stands in for the MCP client, returning a real `@tool` the *real* ToolNode
  executes, and recording the access token it was handed (so we prove the operator's token reaches it).

The capability is OFF by default, so the optional `langchain-mcp-adapters` dependency is never
imported on the flag-off path — asserted below, which is why the whole suite stays green without the
`workspace` extra installed.
"""

from __future__ import annotations

import sys

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool, ToolException, tool
from langgraph.checkpoint.memory import InMemorySaver

from nora.config import Settings
from nora.orchestrator import build_orchestrator
from nora.schemas import RouteDecision
from nora.workspace.graph import build_workspace_agent
from tests.fakes import ScriptedChatModel, ScriptedStructuredModel, ai_final, ai_tool_call


def _stub_node(*args, **kwargs):  # noqa: ARG001 — never reached on a workspace-routed turn
    raise AssertionError("only the workspace capability should run on a workspace request")


class RecordingToolsProvider:
    """A fake `tools_provider`: records every access token it's handed and returns a single recording
    `send_email` tool, so a test can assert both that the operator's token flowed through and that the
    real ToolNode actually ran the tool."""

    def __init__(self):
        self.access_tokens: list[str] = []
        self.sent: list[dict] = []

    def __call__(self, *, access_token: str):
        self.access_tokens.append(access_token)
        sent = self.sent

        @tool
        def send_email(to: str, body: str) -> str:
            """Send an email on the operator's behalf."""
            sent.append({"to": to, "body": body})
            return f"sent to {to}"

        return [send_email]


class AsyncOnlyToolsProvider:
    """Like `RecordingToolsProvider`, but its `send_email` is a **coroutine-only** `StructuredTool` —
    a faithful stand-in for a real MCP tool, which `langchain-mcp-adapters` exposes with no sync
    implementation. Calling `.invoke()` on it raises `NotImplementedError: StructuredTool does not
    support sync invocation` (the production failure), while `.ainvoke()` works. This is what locks in
    the `asyncio.run(agent.ainvoke(...))` fix: a regression to a sync `agent.invoke(...)` would drive
    the tool synchronously and break, where the sync `@tool` in `RecordingToolsProvider` would not."""

    def __init__(self):
        self.access_tokens: list[str] = []
        self.sent: list[dict] = []

    def __call__(self, *, access_token: str):
        self.access_tokens.append(access_token)
        sent = self.sent

        async def send_email(to: str, body: str) -> str:
            sent.append({"to": to, "body": body})
            return f"sent to {to}"

        return [
            StructuredTool.from_function(
                coroutine=send_email,
                name="send_email",
                description="Send an email on the operator's behalf.",
            )
        ]


def _workspace_orch(workspace_agent):
    """Orchestrator wired to route to `workspace`, with stubbed analytics/marketing (never reached)
    so no provider key is needed — the workspace analogue of `_routing_orch`."""
    return build_orchestrator(
        # Pin workspace_enabled=False (an explicit kwarg overrides any local .env) so the flag-off
        # default-build path is deterministic regardless of the developer's NORA_WORKSPACE_ENABLED.
        settings=Settings(workspace_enabled=False),
        router_model=ScriptedStructuredModel(
            {RouteDecision: [RouteDecision(capability="workspace", reason="email")]}
        ),
        analytics_graph=_stub_node,
        marketing_graph=_stub_node,
        workspace_agent=workspace_agent,
        checkpointer=InMemorySaver(),
    )


def test_workspace_runs_the_tool_loop_with_the_operator_token():
    """Routes to workspace, runs the loop against the real ToolNode + the fake tool, and the
    operator's per-run access token reaches the tools provider."""
    model = ScriptedChatModel(
        [
            ai_tool_call(
                "send_email",
                {"to": "priya@example.com", "body": "The cloves shipment is delayed two days."},
                "call-1",
            ),
            ai_final("Sent the email to Priya about the delayed cloves shipment."),
        ]
    )
    provider = RecordingToolsProvider()
    agent = build_workspace_agent(model=model, tools_provider=provider)
    orch = _workspace_orch(agent)

    result = orch.invoke(
        {"messages": [HumanMessage("email priya that the cloves shipment is delayed")]},
        {"configurable": {"thread_id": "w-1", "google_access_token": "tok-123"}},
    )

    assert result["route"]["capability"] == "workspace"
    assert provider.access_tokens == ["tok-123"]  # the operator's token flowed to the MCP client seam
    assert provider.sent == [
        {"to": "priya@example.com", "body": "The cloves shipment is delayed two days."}
    ]  # the *real* ToolNode executed the tool the model chose
    assert "Sent the email to Priya" in result["messages"][-1].content


def test_workspace_loop_drives_async_only_mcp_tools():
    """Regression guard for the `asyncio.run(agent.ainvoke(...))` fix: MCP tools are coroutine-only,
    so the loop MUST run on the async path. A revert to a sync `agent.invoke(...)` would raise
    `NotImplementedError: StructuredTool does not support sync invocation` (it isn't a `ToolException`,
    so `handle_workspace_error` can't absorb it) — the tool would never run and `sent` would stay empty."""
    model = ScriptedChatModel(
        [
            ai_tool_call(
                "send_email",
                {"to": "priya@example.com", "body": "The cloves shipment is delayed two days."},
                "call-1",
            ),
            ai_final("Sent the email to Priya about the delayed cloves shipment."),
        ]
    )
    provider = AsyncOnlyToolsProvider()
    agent = build_workspace_agent(model=model, tools_provider=provider)
    orch = _workspace_orch(agent)

    result = orch.invoke(
        {"messages": [HumanMessage("email priya that the cloves shipment is delayed")]},
        {"configurable": {"thread_id": "w-async", "google_access_token": "tok-123"}},
    )

    # The coroutine-only tool actually executed — proves the loop ran via ainvoke, not a sync invoke.
    assert provider.sent == [
        {"to": "priya@example.com", "body": "The cloves shipment is delayed two days."}
    ]
    assert "Sent the email to Priya" in result["messages"][-1].content


def test_workspace_tool_failure_becomes_a_self_correction_message():
    """A recoverable tool failure (ToolException) is converted by the narrow handle_workspace_error
    into a ToolMessage the model reads and self-corrects from — the analytics-contrast teaching point.
    Real MCP tools raise ToolException because the provider mints them with handle_tool_errors=False
    (>=0.3.0); here a fake tool raises it directly to exercise the same ToolNode path."""

    def provider(*, access_token):  # noqa: ARG001 — token unused by the fake
        @tool
        def send_email(to: str, body: str) -> str:
            """Send an email on the operator's behalf."""
            raise ToolException("recipient address not found")

        return [send_email]

    model = ScriptedChatModel(
        [
            ai_tool_call("send_email", {"to": "bad", "body": "hi"}, "c1"),
            ai_final("I couldn't send it — the address looked wrong; can you confirm it?"),
        ]
    )
    agent = build_workspace_agent(model=model, tools_provider=provider)
    orch = _workspace_orch(agent)

    result = orch.invoke(
        {"messages": [HumanMessage("email someone")]},
        {"configurable": {"thread_id": "w-err", "google_access_token": "tok"}},
    )

    # The ToolException flowed through our handle_workspace_error → a curated ToolMessage, and the
    # model read it and produced a graceful final answer (self-correction, not a crash).
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert any("Re-read the available tools" in (m.content or "") for m in tool_msgs)
    assert "couldn't send it" in result["messages"][-1].content


def test_workspace_degrades_without_a_token():
    """No per-run Google token (operator hasn't connected) → a friendly 'connect' reply, no crash,
    and the agent/tools are never invoked."""
    provider = RecordingToolsProvider()
    agent = build_workspace_agent(model=ScriptedChatModel([]), tools_provider=provider)
    orch = _workspace_orch(agent)

    result = orch.invoke(
        {"messages": [HumanMessage("email priya the shipment is delayed")]},
        {"configurable": {"thread_id": "w-2"}},  # no google_access_token
    )

    assert "connect your google workspace" in result["messages"][-1].content.lower()
    assert provider.access_tokens == []  # the agent must not run without a token


def test_workspace_disabled_needs_no_mcp_dependency():
    """Flag OFF (no workspace_agent injected, the default) → routing to workspace still yields the
    'connect' reply and never imports the optional langchain-mcp-adapters extra."""
    orch = _workspace_orch(None)  # workspace_agent=None mirrors the flag-off default

    result = orch.invoke(
        {"messages": [HumanMessage("send an email for me")]},
        {"configurable": {"thread_id": "w-3", "google_access_token": "tok-123"}},
    )

    assert "connect your google workspace" in result["messages"][-1].content.lower()
    # The base/offline path must not pull the optional MCP adapter (it's the `workspace` extra).
    assert "langchain_mcp_adapters" not in sys.modules
