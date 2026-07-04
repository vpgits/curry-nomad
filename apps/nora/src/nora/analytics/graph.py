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
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime

from nora.analytics.prompts import build_system_prompt
from nora.analytics.tools import ANALYTICS_TOOLS, _get_db
from nora.config import Settings, get_settings
from nora.memory import DEFINITIONS
from nora.observability import get_logger
from nora.services.interfaces import SqlError
from nora.state import AnalyticsState

log = get_logger(__name__)


def _last_user_text(messages: list) -> str:
    """The most recent human message text, used to query metric definitions from memory."""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message.content if isinstance(message.content, str) else str(message.content)
    return ""


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
    """Continue to the tools node iff the model asked for a tool; otherwise finish.

    (Kept as the plain router — `workspace/graph.py` reuses it. The analytics loop uses
    `route_after_llm` below, which adds the 'engage the data before ending' guard.)"""
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else END


# The names of the analytics tools that touch the database — used by the query guard to tell whether
# the agent actually engaged the data this turn (vs. just narrating that it would).
ANALYTICS_TOOL_NAMES = frozenset(tool.name for tool in ANALYTICS_TOOLS)

# Appended to the system prompt on the one guard retry: the model gave a tool-less reply but never
# queried — push it to actually use the tools instead of answering from memory or stating intent.
QUERY_NUDGE = (
    "You replied without using any tool, but never queried the database. If answering needs data, "
    "call the tools now (describe_table to confirm names, then run_sql) and base your answer on the "
    "real result — do not answer from memory or merely state that you are going to look. If the "
    "question genuinely needs no data, answer it directly and concisely."
)


def _last_human_index(messages: list) -> int:
    """Index of the most recent user message — the start of 'this turn'."""
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return i
    return -1


def _used_tool_this_turn(messages: list) -> bool:
    """Did the agent run any analytics (DB) tool since the latest user message? Scoped per-turn so a
    prior turn's query doesn't mask this turn's 'never queried' failure."""
    return any(
        isinstance(m, ToolMessage) and getattr(m, "name", None) in ANALYTICS_TOOL_NAMES
        for m in messages[_last_human_index(messages) + 1 :]
    )


def _bare_answers_this_turn(messages: list) -> int:
    """Count tool-less AIMessage 'answers' since the latest user message — bounds the guard to a
    single retry (so a genuine no-data answer, or a stubborn model, still terminates)."""
    return sum(
        1
        for m in messages[_last_human_index(messages) + 1 :]
        if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None)
    )


def route_after_llm(state: AnalyticsState) -> Literal["tools", "llm", "__end__"]:
    """Analytics router with a 'must engage the data before ending' guard.

    Like `should_continue` (tool_calls → tools, else end) — but it catches the observed failure where
    the model *narrates* intent ("I'm going to check the sales data…") and stops WITHOUT ever calling
    a tool. On a tool-less reply, if no DB tool has run this turn, it loops back to `llm` once (the llm
    node then appends `QUERY_NUDGE`). Bounded to a single retry and only fires when the agent never
    touched the DB, so a normal query→answer turn is untouched and a stubborn/no-data answer still
    terminates. Stateless — reads only messages since the last user turn."""
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    if not _used_tool_this_turn(state["messages"]) and _bare_answers_this_turn(state["messages"]) <= 1:
        log.info("analytics.query_nudge")
        return "llm"
    return END


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
        # The analytics agent is added to the orchestrator as a real subgraph *node* (not invoked
        # imperatively), so its messages stream live into the top-level thread — the tool-call steps
        # AND the final answer render inline. `streaming=True` makes each LLM call emit token deltas
        # (the user-facing answer streams token-by-token); the client opts into nested-graph messages
        # with `streamSubgraphs: true`. (The router/dashboard/marketing models set disable_streaming
        # — their calls never become user-facing text; see orchestrator.py.)
        model_id = settings.model_for("analytics")  # per-node override, else the base `model`
        if settings.thinking_budget > 0 and model_id.startswith("anthropic:"):
            # Opt-in (NORA_THINKING_BUDGET): surface the agent's reasoning chain in the chat. With
            # Anthropic extended thinking, each AIMessage carries `thinking` content blocks that
            # stream inline next to the tool steps. Thinking requires temperature=1 (no 0), and
            # max_tokens must exceed the thinking budget — so we size it above the budget.
            model = init_chat_model(
                model_id,
                temperature=1,
                streaming=True,
                max_tokens=settings.thinking_budget + 4096,
                thinking={"type": "enabled", "budget_tokens": settings.thinking_budget},
            )
        else:
            model = init_chat_model(model_id, temperature=0, streaming=True)
    model_with_tools = model.bind_tools(ANALYTICS_TOOLS)

    # The table list is static for a given DB; fetch it once at build time.
    table_names = _get_db().list_tables()

    def llm_node(state: AnalyticsState, runtime: Runtime) -> dict:
        # Long-term memory (M3): pull metric definitions relevant to the question from the
        # Store via runtime.store, and fold them into the system prompt so they shape the SQL.
        definitions = ""
        # Deliberately the runtime-injected store, NOT the build-time `store` param: on the platform
        # (Aegra) the store is injected at runtime and lives on `runtime`, so the build closure's may
        # be None. Named distinctly so this intent isn't "fixed" into a bug.
        runtime_store = getattr(runtime, "store", None)
        if runtime_store is not None:
            query = _last_user_text(state["messages"]) or "metric definitions"
            items = runtime_store.search(DEFINITIONS, query=query, limit=3)
            definitions = "\n".join(item.value["text"] for item in items)
        system = build_system_prompt(table_names, settings, definitions=definitions)
        # Query guard (see route_after_llm): if the model already gave a tool-less reply this turn but
        # never touched the DB, it likely narrated intent and stopped — append the nudge so this retry
        # actually uses the tools. The nudge lives in the ephemeral system prompt (rebuilt each call),
        # so it never leaks into the shared `messages` channel.
        if _bare_answers_this_turn(state["messages"]) >= 1 and not _used_tool_this_turn(state["messages"]):
            system += "\n\n" + QUERY_NUDGE
        response = model_with_tools.invoke([SystemMessage(content=system), *state["messages"]])
        # Termination guard (mirrors the prebuilt create_agent): if the step budget is nearly spent
        # but the model still wants to call tools, stop with a plain answer instead of looping into a
        # GraphRecursionError. Analytics runs as a subgraph node, so an unhandled recursion error would
        # crash the whole turn; degrading to text keeps the turn alive. `remaining_steps` is a managed
        # value, auto-populated from the run's recursion_limit.
        if state.get("remaining_steps", 99) <= 2 and getattr(response, "tool_calls", None):
            return {
                "messages": [
                    AIMessage(
                        content="I wasn't able to finish that analysis within the available steps. "
                        "Try narrowing the question — a specific metric, product, or time window."
                    )
                ]
            }
        return {"messages": [response]}

    builder = StateGraph(AnalyticsState)
    builder.add_node("llm", llm_node)
    builder.add_node("tools", ToolNode(ANALYTICS_TOOLS, handle_tool_errors=handle_sql_error))
    builder.add_edge(START, "llm")
    # route_after_llm adds the query guard: tool_calls → tools, a tool-less reply that never queried →
    # back to "llm" once (with QUERY_NUDGE), otherwise END.
    builder.add_conditional_edges("llm", route_after_llm, ["tools", "llm", END])
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
