"""The workspace agent loop (hand-built, mirroring the analytics agent).

    START → llm → should_continue → (tools | END)
    tools → llm                                  # loop back

Same shape as `analytics/graph.py`, with one deliberate twist: the tool set is **built per run
from the operator's MCP client** (whose bearer token is *this operator's* Google OAuth access
token), not bound once at compile time. So instead of compiling a static subgraph, we expose a
`build_workspace_agent(...)` that returns a callable; each call binds the per-run tools, compiles a
one-shot loop, and runs it.

Why a fresh connection per run: `langchain-mcp-adapters` can't swap a per-request bearer on a
long-lived client, so we mint a new per-run connection each turn with
`headers={"Authorization": "Bearer …"}`.

The default tools provider — the only place `langchain_mcp_adapters` is imported — is created lazily
and imported lazily, so the base install never pulls the optional dependency and the offline test
suite stays green (the capability is OFF by default; tests inject a fake provider).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.tools import BaseTool, ToolException
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from nora.analytics.graph import should_continue  # reuse: "tools" if last.tool_calls else END
from nora.config import Settings, get_settings
from nora.observability import get_logger
from nora.state import AnalyticsState

log = get_logger(__name__)

# A callable that mints the operator's Google Workspace tools for one run, given their access token.
# Injectable (the analogue of routing's `route_planner`) so offline tests pass a fake — no MCP server,
# no network. The default implementation builds a per-run MultiServerMCPClient (see below).
ToolsProvider = Callable[..., Sequence[BaseTool]]

WORKSPACE_SYSTEM_PROMPT = (
    "You are Nora, Curry Nomad's operations assistant, acting on the operator's own Google "
    "Workspace account. Use the available tools to carry out the request — send or draft an email, "
    "read or create a calendar event, etc. Only claim an action you actually performed via a tool; "
    "never fabricate a result. When done, reply with a short, plain confirmation of what you did "
    "(who/what/when), or ask one concise clarifying question if the request is ambiguous."
)


def handle_workspace_error(error: ToolException) -> str:
    """Turn a recoverable MCP tool failure into the ToolMessage the model sees, so it can self-correct.

    Annotated with `ToolException` (LangChain's native "the tool failed, recoverably" signal) so
    ToolNode catches *only* that — transport/auth errors (e.g. a 401 from a dead token) propagate and
    fail loud / degrade in the orchestrator node, which is correct: those aren't "rephrase and retry"
    situations. Mirrors `analytics.graph.handle_sql_error`'s narrow-catch discipline; don't broaden it.
    """
    log.info("workspace.tool_error", error=str(error))
    return (
        f"That tool call failed: {error}\n"
        "Re-read the available tools and their arguments, fix the call, and try again."
    )


def _make_mcp_tools_provider(settings: Settings) -> ToolsProvider:
    """The production tools provider: a fresh Google Workspace MCP client per run, keyed by the
    operator's bearer token. This is the ONLY place `langchain_mcp_adapters` is touched, and it's
    imported lazily so the base install (capability OFF) never needs the optional extra."""

    def provider(*, access_token: str) -> Sequence[BaseTool]:
        from langchain_mcp_adapters.tools import load_mcp_tools

        # A fresh per-run connection carrying THIS operator's bearer. `session=None` + `connection=`
        # opens a stateless session per tool call, so nothing is held across the loop.
        connection = {
            "transport": "streamable_http",
            "url": settings.workspace_mcp_url,
            "headers": {"Authorization": f"Bearer {access_token}"},
        }
        # handle_tool_errors=False: make a failed MCP tool call RAISE a ToolException instead of the
        # adapter (its >=0.3.0 default) converting it into a ToolMessage itself — so OUR narrow
        # `handle_workspace_error` in ToolNode stays the demonstrated self-correction mechanism (the
        # analytics-contrast teaching point). `load_mcp_tools` is async; we're in a sync graph node
        # off the event loop, so a one-shot `asyncio.run` is safe (same bridge as the loop driver).
        return asyncio.run(
            load_mcp_tools(None, connection=connection, handle_tool_errors=False)
        )

    return provider


def _compile_loop(model, tools: Sequence[BaseTool]):
    """Compile the analytics-style llm↔tools loop for one run's tool set (see module docstring)."""
    model_with_tools = model.bind_tools(tools)

    def llm_node(state: AnalyticsState) -> dict:
        response = model_with_tools.invoke(
            [SystemMessage(content=WORKSPACE_SYSTEM_PROMPT), *state["messages"]]
        )
        # Same termination guard as analytics (this loop reuses AnalyticsState's `remaining_steps`):
        # if the step budget is nearly spent but the model still wants tools, stop with a plain
        # answer instead of looping into a GraphRecursionError.
        if state.get("remaining_steps", 99) <= 2 and getattr(response, "tool_calls", None):
            return {
                "messages": [
                    AIMessage(
                        content="I couldn't finish that within the available steps — try a more "
                        "specific request."
                    )
                ]
            }
        return {"messages": [response]}

    builder = StateGraph(AnalyticsState)
    builder.add_node("llm", llm_node)
    builder.add_node("tools", ToolNode(tools, handle_tool_errors=handle_workspace_error))
    builder.add_edge(START, "llm")
    builder.add_conditional_edges("llm", should_continue, ["tools", END])
    builder.add_edge("tools", "llm")
    return builder.compile()


def build_workspace_agent(
    *,
    settings: Settings | None = None,
    model=None,
    tools_provider: ToolsProvider | None = None,
):
    """Build the workspace capability runner.

    Returns a callable `run(messages, *, access_token, config=None) -> list[BaseMessage]` that binds
    the operator's per-run MCP tools, runs the tool loop, and returns ONLY the new messages (the
    tool-call steps + final answer) so they merge into the top-level thread and render inline (the
    model streams, like analytics — its tokens are the answer).

    `model` and `tools_provider` are injectable for offline tests (a `ScriptedChatModel` + a fake
    tool list); by default the model is built from settings (lazily, so building the agent needs no
    provider key) and the tools come from the real MCP client.
    """
    settings = settings or get_settings()
    provider = tools_provider or _make_mcp_tools_provider(settings)
    _model = model  # may be None → built lazily on first run (so flag-on build needs no key at import)

    def run(messages: list, *, access_token: str, config=None) -> list[BaseMessage]:
        nonlocal _model
        if _model is None:
            _model = init_chat_model(settings.model, temperature=0, streaming=True)
        tools = provider(access_token=access_token)
        agent = _compile_loop(_model, tools)
        # MCP tools (langchain-mcp-adapters) are ASYNC-ONLY — a sync `.invoke()` raises "StructuredTool
        # does not support sync invocation". So drive the loop with `ainvoke`, which executes tools via
        # their async path. We're in a sync graph node running off the event loop (Aegra runs sync
        # nodes in a worker thread; the CLI/tests have no running loop), so a one-shot `asyncio.run` is
        # safe — the same bridge the tools_provider uses for `get_tools()`.
        result = asyncio.run(agent.ainvoke({"messages": messages}, config))
        # Return only the tail the agent appended (add_messages keeps input messages at the front by
        # id), so we don't re-emit the operator's prompt into the top-level thread.
        return list(result["messages"][len(messages) :])

    return run
