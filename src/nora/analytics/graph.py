"""The analytics agent loop (hand-built — the teaching centerpiece).

    START → llm → should_continue → (tools | END)
    tools → llm                                  # loop back

The loop is written out explicitly (rather than using `create_agent`) so the mechanism is
visible: the model proposes tool calls, `ToolNode` runs them, and a failed `run_sql` comes
back as a ToolMessage (the DB error) so the model can repair and retry. The production
shortcut — the same thing in ~5 lines with `create_agent` — is in the appendix at the bottom.
"""

from __future__ import annotations

from typing import Literal

from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from nora.analytics.prompts import build_system_prompt
from nora.analytics.tools import ANALYTICS_TOOLS, _get_db
from nora.config import Settings, get_settings
from nora.observability import get_logger
from nora.services.interfaces import SqlError
from nora.state import AnalyticsState

log = get_logger(__name__)


def handle_sql_error(error: SqlError) -> str:
    """Turn a raised SqlError into the ToolMessage the model sees, enabling self-correction.

    The first-parameter annotation (`SqlError`) tells ToolNode to handle *only* SqlError —
    any other exception propagates and fails loudly (no swallowed bugs).
    """
    log.info("sql.error", error=str(error))
    return (
        f"Your query failed: {error}\n"
        "Call describe_table to confirm the exact table/column names, then fix the SQL and "
        "run it again."
    )


def should_continue(state: AnalyticsState) -> Literal["tools", "__end__"]:
    """Continue to the tools node iff the model asked for a tool; otherwise finish."""
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else END


def build_analytics_graph(
    *,
    settings: Settings | None = None,
    model=None,
    checkpointer=None,
    store=None,
):
    """Compile the analytics agent subgraph.

    `model` can be injected (e.g. a scripted fake in tests); otherwise it is built from the
    config string via `init_chat_model`. `checkpointer`/`store` are optional so the subgraph
    is independently runnable and testable before the orchestrator wires them in (M4).
    """
    settings = settings or get_settings()
    if model is None:
        model = init_chat_model(settings.model, temperature=0)
    model_with_tools = model.bind_tools(ANALYTICS_TOOLS)

    # The table list is static for a given DB; fetch it once at build time.
    table_names = _get_db().list_tables()

    def llm_node(state: AnalyticsState) -> dict:
        system = build_system_prompt(table_names, settings)
        response = model_with_tools.invoke([SystemMessage(content=system), *state["messages"]])
        return {"messages": [response]}

    builder = StateGraph(AnalyticsState)
    builder.add_node("llm", llm_node)
    builder.add_node("tools", ToolNode(ANALYTICS_TOOLS, handle_tool_errors=handle_sql_error))
    builder.add_edge(START, "llm")
    builder.add_conditional_edges("llm", should_continue, ["tools", END])
    builder.add_edge("tools", "llm")
    return builder.compile(checkpointer=checkpointer, store=store)


# --- Production shortcut (appendix) ---------------------------------------------------
#
# In production you would not hand-write the loop above — you'd use the prebuilt agent, which
# hides exactly the wiring we just spelled out (loop, tool execution, error handling):
#
#   from langchain.agents import create_agent
#   from langchain.agents.middleware import wrap_tool_call
#
#   agent = create_agent(
#       model="openai:gpt-4o",
#       tools=ANALYTICS_TOOLS,
#       system_prompt=build_system_prompt(table_names, settings),
#       checkpointer=checkpointer,
#       # tool-error handling is middleware here (not ToolNode):
#       # middleware=[wrap_tool_call(...)],
#   )
#   result = agent.invoke({"messages": [...]})
#
# We build it by hand so the loop, the router (`should_continue`), and the self-correction
# mechanism are all visible and teachable.
