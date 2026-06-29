"""The orchestrator graph — a supervisor over the capabilities (the entry point).

    START → supervisor ⇄ { analytics | marketing | workspace } → (supervisor) → END

A coordinating **supervisor** (the "main agent") reads the conversation and delegates to one
specialist capability at a time by calling a handoff tool (`to_analytics` / `to_marketing` /
`to_workspace`). Each capability runs as a graph node and **returns to the supervisor**, so the
supervisor can chain them in a single turn — e.g. answer a data question, THEN build a brief from
that answer. When the specialists have handled the request the supervisor stops (and stays silent,
since the capability already answered inline); for an ambiguous request it replies with a short
clarifying question instead of delegating.

Capabilities are a deliberate mix of shapes the supervisor doesn't have to care about: compiled
subgraph nodes (analytics, workspace — they share the chat `messages` channel and stream inline)
and an imperative function node (marketing — its workflow state is disjoint, so it wraps the
subgraph and translates in/out). Passing each node's `config` through means a HITL interrupt inside
the marketing subgraph bubbles up and pauses the whole orchestrator, and a `Command(resume=...)` on
the same thread_id flows back down into it.

The supervisor itself uses `disable_streaming=True` (its handoff tool-calls are control plumbing,
never user-facing text — same reason the dashboard/marketing models disable streaming); the
*answer* the user sees streams from the capabilities, whose tokens ARE the answer.
"""

from __future__ import annotations

from typing import Literal

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.ui import push_ui_message
from langgraph.types import Command

from nora.analytics.graph import build_analytics_graph
from nora.config import Settings, get_settings
from nora.marketing.graph import build_marketing_graph, initial_marketing_state
from nora.observability import get_logger
from nora.schemas import AnalyticsDashboard, Context
from nora.state import OrchestratorState

log = get_logger(__name__)


# --- The supervisor's handoff tools -----------------------------------------------------
# These are never executed: the supervisor model *calls* one to signal a delegation, and the
# supervisor node reads that tool-call and dispatches with Command(goto=...). They exist only for
# their schema (name + args), which is what `bind_tools` shows the model.


@tool
def to_analytics(task: str) -> str:
    """Delegate to the analytics agent: answer a question about business data/metrics (sales,
    revenue, products, customers, refunds, channels, time windows) by querying the database.
    `task` is a clear, self-contained instruction for the analyst."""
    return ""


@tool
def to_marketing(task: str, product_hint: str | None = None) -> str:
    """Delegate to the marketing studio: CREATE a video ad / reel / creative for a product.
    `task` describes the creative request; set `product_hint` to the product's name when one is
    identifiable (resolve 'it'/'that one' from the conversation)."""
    return ""


@tool
def to_workspace(task: str) -> str:
    """Delegate to the workspace agent: act on the operator's own Google account — draft or send
    an email (Gmail), or read/create a calendar event. `task` is the action to carry out."""
    return ""


HANDOFF_TOOLS = [to_analytics, to_marketing, to_workspace]
HANDOFF_TARGET = {"to_analytics": "analytics", "to_marketing": "marketing", "to_workspace": "workspace"}
# Loop guard: cap how many capability hops one turn may chain, so the supervisor can't delegate
# forever (belt-and-braces with the run's recursion_limit).
MAX_DELEGATIONS = 6

SUPERVISOR_INSTRUCTIONS = (
    "You are the supervisor for Nora, Curry Nomad's operations assistant. You coordinate three "
    "specialist capabilities by delegating with the handoff tools — you do NOT do their work "
    "yourself:\n"
    "- to_analytics: business data/metrics questions (sales, revenue, products, customers, "
    "refunds, channels, time windows), answered by querying the database.\n"
    "- to_marketing: CREATE a video ad / reel / creative for a product.\n"
    "- to_workspace: act on the operator's own Google account — draft or send an email (Gmail), "
    "read or create a calendar event.\n\n"
    "Rules:\n"
    "1. To use a capability, call its handoff tool with a clear, self-contained `task`. For a "
    "marketing request set `product_hint` to the product's name (resolve 'it'/'that one' from the "
    "conversation).\n"
    "2. You may delegate more than once to CHAIN capabilities — e.g. analyze data, THEN create a "
    "brief from the result. Delegate one capability at a time; its result comes back to you.\n"
    "3. When the specialists have fully handled the request, STOP — do not call another tool and "
    "do not restate their answer; just end.\n"
    "4. If the request is ambiguous or matches no capability, do NOT call a tool — reply with one "
    "short clarifying question (ask whether they want a data answer or a video ad, and for which "
    "product)."
)

# Shown when the supervisor itself fails (a flaky classifier shouldn't crash the turn).
CLARIFY_TEXT = (
    "I can answer a question about the business data, or create a video ad for a product. Which "
    "would you like — and for which product?"
)

# Shown when the workspace capability is unavailable (flag off, or no Google token connected yet).
CONNECT_MSG = (
    "Connect your Google Workspace and I can act on your Gmail and Calendar — use the “Connect "
    "Google Workspace” button, then ask me again."
)


def _last_user_text(messages: list) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message.content if isinstance(message.content, str) else str(message.content)
    return ""


def _handoff_count(messages: list) -> int:
    """How many times the supervisor has already delegated this thread — the loop-guard counter."""
    return sum(
        1
        for m in messages
        for tc in (getattr(m, "tool_calls", None) or [])
        if tc.get("name") in HANDOFF_TARGET
    )


def _capability_answered_this_turn(messages: list) -> bool:
    """True if a capability has produced a user-facing answer since the last user message — a
    content-bearing AIMessage with no tool calls. Lets the supervisor end SILENTLY rather than
    restate an answer a capability already streamed into the thread (the supervisor's own delegating
    messages carry handoff tool_calls, so they don't count)."""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return False
        if isinstance(m, AIMessage) and m.content and not getattr(m, "tool_calls", None):
            return True
    return False


DASHBOARD_INSTRUCTIONS = (
    "Compose a compact operator dashboard from this analytics answer. Extract 1-4 headline stats "
    "as label + a pre-formatted value (e.g. value 'LKR 105,850', '73', '4.2%'). If the data is "
    "naturally tabular, add a small table (<= 6 rows) of stringified cells. "
    "Also CHOOSE a chart when the data suits one — this is the point: pick the kind that fits the "
    "shape. A trend over time → kind 'line'; a ranking or comparison across categories → kind "
    "'bar'; a part-of-whole breakdown (shares that sum to a whole) → kind 'pie'; otherwise kind "
    "'none'. Give up to ~8 series points (short label + numeric value), and set x_label/y_label "
    "for bar/line; keep the series consistent with the table when both are present. If nothing is "
    "dashboard-worthy (a single trivial number, or a non-data answer), return empty stats, no "
    "table, and chart kind 'none'."
)


def _sql_results_from_messages(messages: list) -> str:
    """Collect the run_sql results from the agent's tool messages, for the dashboard's context.

    With the analytics agent running as a subgraph node, its run_sql calls and their ToolMessage
    results are now inline messages in the thread — pair each run_sql call to its result by id."""
    run_sql_ids = {
        tc.get("id")
        for m in messages
        for tc in (getattr(m, "tool_calls", None) or [])
        if tc.get("name") == "run_sql"
    }
    parts = []
    for m in messages:
        if getattr(m, "tool_call_id", None) in run_sql_ids:
            content = m.content
            parts.append(content if isinstance(content, str) else str(content))
    return "\n\n".join(parts)


def _build_dashboard(model, answer: str, query_results: str) -> AnalyticsDashboard | None:
    """Best-effort generative-UI dashboard from the final answer + the SQL the agent ran.

    Returns None (and the caller renders nothing) when generation fails or the answer isn't
    dashboard-worthy — generative UI is a nicety, never load-bearing for the text answer."""
    if not answer.strip():
        return None
    context = f"Answer:\n{answer}"
    if query_results:
        context += f"\n\nQuery results the answer is based on:\n{query_results[:2000]}"
    try:
        dashboard: AnalyticsDashboard = model.with_structured_output(AnalyticsDashboard).invoke(
            [SystemMessage(content=DASHBOARD_INSTRUCTIONS), HumanMessage(content=context)]
        )
    except Exception as exc:  # noqa: BLE001 — optional generative UI: never break the text answer
        log.info("dashboard.skipped", error=str(exc))
        return None
    has_chart = (
        dashboard.chart is not None
        and dashboard.chart.kind != "none"
        and bool(dashboard.chart.series)
    )
    if not dashboard.stats and dashboard.table is None and not has_chart:
        return None
    log.info(
        "dashboard.built",
        stats=len(dashboard.stats),
        has_table=dashboard.table is not None,
        chart=dashboard.chart.kind if has_chart else "none",
    )
    return dashboard


def build_orchestrator(
    *,
    settings: Settings | None = None,
    supervisor_model=None,
    analytics_graph=None,
    marketing_graph=None,
    dashboard_model=None,
    workspace_agent=None,
    checkpointer=None,
    store=None,
):
    """Compile the orchestrator. Subgraphs/supervisor are injectable for offline tests; by default
    they're built from settings and share the orchestrator's `store` (so memory works) while
    relying on the orchestrator's `checkpointer` for HITL (passed via each node's config)."""
    settings = settings or get_settings()
    if supervisor_model is None:
        # disable_streaming: the supervisor delegates via handoff tool-calls (control plumbing), not
        # user-facing text. With streaming on, Aegra's `messages` stream still emits those internal
        # tool-call deltas (it captures every LLM call via callbacks), so the useStream UI would
        # briefly render a phantom partial message for a delegation. Disabling streaming keeps the
        # supervisor off the token stream; the user-facing ANSWER streams from the capabilities,
        # whose tokens ARE the answer. (The dashboard and marketing models disable streaming for the
        # same reason; the analytics agent keeps streaming on.)
        supervisor_model = init_chat_model(
            settings.router_model, temperature=0, disable_streaming=True
        )
    if analytics_graph is None:
        analytics_graph = build_analytics_graph(settings=settings, store=store)
    if marketing_graph is None:
        # auto_choose=False adds the interactive concept-pick gate (generative-UI selection) before
        # the script-review gate; the app surfaces both, evals/tests keep the single script gate.
        marketing_graph = build_marketing_graph(
            settings=settings, store=store, auto_approve=False, auto_choose=False
        )
    if dashboard_model is None:
        # Composes the generative-UI dashboard from an analytics answer — a with_structured_output
        # call whose result never lands in `messages`, so disable_streaming for the same reason as
        # the supervisor (above). Construction needs a provider key; without one (e.g. offline tests
        # that don't inject a fake) we simply disable the dashboard — never the text answer.
        try:
            dashboard_model = init_chat_model(settings.model, temperature=0, disable_streaming=True)
        except Exception:  # noqa: BLE001 — no key → dashboards off, the rest of the app still runs
            dashboard_model = None
    if workspace_agent is None and settings.workspace_enabled:
        # Build the workspace capability ONLY when the flag is on — the import (and thus
        # langchain-mcp-adapters) is deferred so the base install stays dependency-light and the
        # offline suite (flag off) never needs the optional extra. When off, `workspace_agent` stays
        # None and the node degrades to a friendly "connect" reply (see below).
        from nora.workspace.graph import build_workspace_agent as _build_workspace_agent

        workspace_agent = _build_workspace_agent(settings=settings)

    def supervisor(
        state: OrchestratorState,
    ) -> Command[Literal["analytics", "marketing", "workspace", "__end__"]]:
        # The coordinating "main agent": read the conversation, delegate to one capability (a handoff
        # tool-call → Command(goto=...)), or finish. Capabilities return here, so it can chain them.
        messages = state["messages"]
        capped = _handoff_count(messages) >= MAX_DELEGATIONS
        # Past the delegation cap → drop the tools so the model can only answer (no more hops).
        model = supervisor_model if capped else supervisor_model.bind_tools(HANDOFF_TOOLS)
        instructions = SUPERVISOR_INSTRUCTIONS + (
            "\n\nYou have delegated as much as allowed — answer the user directly now; do not "
            "delegate." if capped else ""
        )
        try:
            ai = model.invoke([SystemMessage(content=instructions), *messages])
        except Exception as exc:  # noqa: BLE001 — a flaky supervisor shouldn't crash the turn
            log.info("supervisor.failed", error=str(exc))
            return Command(goto=END, update={"messages": [AIMessage(content=CLARIFY_TEXT)]})

        calls = [c for c in (getattr(ai, "tool_calls", None) or []) if c.get("name") in HANDOFF_TARGET]
        if calls:
            first = calls[0]
            target = HANDOFF_TARGET[first["name"]]
            # Ack EVERY tool-call the model made (the next supervisor turn rejects an unanswered
            # tool_call), but hand off only to the first — capabilities run one at a time.
            acks = [
                ToolMessage(
                    content=f"Handing off to {HANDOFF_TARGET[c['name']]}.", tool_call_id=c["id"]
                )
                for c in calls
            ]
            args = first.get("args") or {}
            log.info("route.decided", capability=target, task=args.get("task"))
            return Command(
                goto=target,
                update={"messages": [ai, *acks], "handoff": {"target": target, **args}},
            )

        # No handoff → the turn is done. Stay SILENT if a capability already answered (its answer is
        # the reply); otherwise this is a clarification (or a no-capability reply) — surface the text.
        if _capability_answered_this_turn(messages):
            log.info("supervisor.done")
            return Command(goto=END)
        log.info("supervisor.clarify")
        return Command(goto=END, update={"messages": [ai]})

    def analytics_dashboard(state: OrchestratorState) -> dict:
        # Runs right AFTER the analytics agent subgraph node. The agent's full tool loop — its
        # run_sql calls, their results, and the streamed final answer — has already flowed into the
        # top-level thread as inline messages (that's the streaming we want). Here we add the one
        # thing that isn't a chat message: the generative-UI dashboard, composed from the final
        # answer + the SQL results the agent saw, pushed via push_ui_message (the useStream UI
        # renders it via LoadExternalComponent). Best-effort — skips silently if generation fails
        # (no provider key offline) or nothing is dashboard-worthy; the answer is never blocked on it.
        if dashboard_model is None:
            return {}
        messages = state["messages"]
        final = messages[-1]
        answer = final.content if isinstance(final.content, str) else str(final.content)
        dashboard = _build_dashboard(dashboard_model, answer, _sql_results_from_messages(messages))
        if dashboard is None:
            return {}
        data = dashboard.model_dump()
        # Same id → add_messages updates the final message in place (no duplicate).
        final.additional_kwargs = {**(final.additional_kwargs or {}), "dashboard": data}
        push_ui_message("analytics_dashboard", data, message=final)
        return {"messages": [final]}

    def marketing(state: OrchestratorState, config) -> dict:
        handoff = state.get("handoff") or {}  # the supervisor's delegation (JSON-native state)
        request = handoff.get("task") or _last_user_text(state["messages"])
        product_hint = handoff.get("product_hint")
        # If the subgraph interrupts (concept_pick / human_review), this bubbles up and pauses the
        # orchestrator; on resume the node re-runs and the subgraph continues from its checkpoint.
        result = marketing_graph.invoke(initial_marketing_state(request, product_hint), config)
        brief = result.get("brief")  # VideoBrief dict, or None if rejected at review
        if brief is None:  # rejected at review
            return {"messages": [AIMessage(content="Creative cancelled — no brief produced.")]}
        # Format the summary + attach the gen-UI cards. Guard THIS post-result block (NOT the
        # `.invoke` above — a HITL GraphInterrupt must still propagate to pause the orchestrator) so a
        # malformed/partial brief degrades to a text reply instead of crashing the turn, matching the
        # workspace node's "never crash, degrade" contract.
        try:
            summary = (
                f"Video brief ready for {brief['product_name']}: \"{brief['concept']}\" — hook: "
                f"\"{brief['hook']}\". {len(brief['shots'])} shots, "
                f"~{brief['target_duration_s']:.0f}s, "
                f"CTA: {brief['cta']}. Render: {result.get('render_result', {}).get('status')}."
            )
            final = AIMessage(content=summary)
            # Generative UI: the finished workflow's artifacts as cards on the same channel the
            # analytics dashboard uses (push_ui_message → LoadExternalComponent). The brief is the
            # headline; storyboard / script-timeline / critique are the supporting detail.
            push_ui_message("video_brief", {"brief": brief}, message=final)
            if result.get("shots"):
                push_ui_message(
                    "marketing_storyboard",
                    {"shots": result["shots"], "shot_prompts": result.get("shot_prompts") or []},
                    message=final,
                )
            if brief.get("script_beats"):
                push_ui_message(
                    "marketing_script_timeline",
                    {"script_beats": brief["script_beats"]},
                    message=final,
                )
            if result.get("critique"):
                push_ui_message("marketing_critique", result["critique"], message=final)
            # Real-render card: hero image + per-shot stills, plus the video job ids the UI polls.
            # Skipped for the placeholder/cancelled renderer (nothing to show).
            render_result = result.get("render_result")
            if render_result and render_result.get("status") in ("rendering", "rendered", "error"):
                push_ui_message("marketing_render", render_result, message=final)
            return {"messages": [final]}
        except Exception as exc:  # noqa: BLE001 — malformed brief → degrade to text, never crash the turn
            log.info("marketing.skipped", error=str(exc))
            return {
                "messages": [
                    AIMessage(
                        content="I put together a creative brief but couldn't assemble the full "
                        "result card — the brief may be incomplete. Please try the request again."
                    )
                ]
            }

    def workspace_stub(state: OrchestratorState) -> dict:
        # Flag OFF (no `workspace_agent` built): a SYNC node that asks the operator to connect. Keeps
        # the default orchestrator all-sync (so it never imports langchain-mcp-adapters and stays
        # sync-invokable in the offline suite); the supervisor still delegates to "workspace".
        return {"messages": [AIMessage(content=CONNECT_MSG)]}

    async def workspace(state: OrchestratorState, config) -> dict:
        # Flag ON: act on the operator's own Google account (Gmail/Calendar) via the Workspace MCP
        # server — an agentic tool loop, ASYNC because MCP tools are coroutine-only (so it `await`s
        # the loop directly on the orchestrator's event loop — no asyncio.run bridge). Needs a per-run
        # Google access token the web client passes in `config.configurable`; missing → connect reply.
        token = (config or {}).get("configurable", {}).get("google_access_token")
        # TODO(prod): the access token rides in run config, which the checkpointer persists. For
        # production, carry it as a claim in the Aegra auth JWT and read it from the authenticated
        # user so it never lands in state. Fine for a Testing-mode demo with short-lived tokens.
        if not token:
            return {"messages": [AIMessage(content=CONNECT_MSG)]}
        try:
            new_messages = await workspace_agent(
                state["messages"], access_token=token, config=config
            )
        except Exception as exc:  # noqa: BLE001 — MCP/transport failure → text reply, never crash
            log.info("workspace.skipped", error=str(exc))
            return {
                "messages": [
                    AIMessage(
                        content="I couldn't reach your Google Workspace just now — is the connection "
                        "still active? Try reconnecting and asking again."
                    )
                ]
            }
        # Tag the turn with a gen-UI marker so the chat shows the "Workspace agent" badge and a
        # compact summary of the Google tools Nora used. Best-effort, like the other cards.
        tools_used = [
            tc.get("name")
            for m in new_messages
            for tc in (getattr(m, "tool_calls", None) or [])
            if tc.get("name")
        ]
        final = next((m for m in reversed(new_messages) if isinstance(m, AIMessage)), None)
        if final is not None:
            push_ui_message("workspace_actions", {"tools": tools_used}, message=final)
        log.info("workspace.completed", new_messages=len(new_messages), tools=len(tools_used))
        return {"messages": new_messages}

    builder = StateGraph(OrchestratorState, context_schema=Context)
    builder.add_node("supervisor", supervisor)
    # Analytics is added as a real subgraph NODE (not invoked imperatively): because it's part of
    # the graph, its messages — the run_sql tool-call steps AND the streamed final answer — flow
    # live into the top-level thread and render inline (clients opt in with `streamSubgraphs: true`).
    # `analytics_dashboard` runs right after to attach the generative-UI card from that answer.
    builder.add_node("analytics", analytics_graph)
    builder.add_node("analytics_dashboard", analytics_dashboard)
    # Marketing is an imperative function node: its workflow state is disjoint from the chat (it
    # produces a structured brief, not a token-streamed reply), and invoking the subgraph with
    # `config` is what lets a HITL interrupt() deep inside it bubble up and pause the orchestrator.
    builder.add_node("marketing", marketing)
    # Workspace: an agentic tool loop over the Google Workspace MCP server — acts on the operator's
    # own Gmail/Calendar. Flag OFF → a sync "connect" stub (keeps the default orchestrator all-sync);
    # flag ON → the async agent node (awaits the per-run MCP loop). The supervisor delegates here
    # either way.
    builder.add_node("workspace", workspace if workspace_agent is not None else workspace_stub)

    builder.add_edge(START, "supervisor")
    # The supervisor dispatches via Command(goto=...). Every capability returns TO the supervisor
    # (not END), so it can decide to chain another capability or finish the turn.
    builder.add_edge("analytics", "analytics_dashboard")
    builder.add_edge("analytics_dashboard", "supervisor")
    builder.add_edge("marketing", "supervisor")
    builder.add_edge("workspace", "supervisor")

    return builder.compile(checkpointer=checkpointer, store=store)


def make_graph():
    """Factory for a platform server (Aegra via aegra.json).

    The platform provides persistence — the Postgres checkpointer (so HITL interrupts persist
    and resume) and the semantic Store (configured under `store.index` in aegra.json). So we
    compile WITHOUT our own: the platform injects them at runtime, and the store propagates into
    the analytics/marketing subgraphs. Seed the Store's brand voice + metric definitions once
    after the server is up with `apps/nora/scripts/seed_store.py`.

    (The CLI in `app.py` is the self-contained path — it builds and seeds its own in-memory
    checkpointer + Store.) Requires provider keys in the environment (it builds real models)."""
    return build_orchestrator(settings=get_settings())
