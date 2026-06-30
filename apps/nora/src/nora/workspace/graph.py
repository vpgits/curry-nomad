"""The workspace agent loop (hand-built, mirroring the analytics agent) — now async.

    START → llm → should_continue → (tools | END)
    tools → llm                                  # loop back

Same shape as `analytics/graph.py`, with one deliberate twist: the tool set is **built per run
from the operator's MCP client** (whose bearer token is *this operator's* Google OAuth access
token), not bound once at compile time. So instead of compiling a static subgraph, we expose a
`build_workspace_agent(...)` that returns an async callable; each call binds the per-run tools,
compiles a one-shot loop, and runs it.

Why a fresh connection per run: `langchain-mcp-adapters` mints a stateless session per tool call,
so we open a new per-run connection carrying THIS operator's bearer in `headers`.

The loop runs **async** (`await agent.ainvoke(...)`): MCP tools are coroutine-only (a sync
`.invoke()` raises "StructuredTool does not support sync invocation"), and the orchestrator now
drives the whole graph async (`astream`/`ainvoke`), so the workspace node simply `await`s — no
`asyncio.run` bridge any more (that only existed when the node was sync).

The default tools provider — the only place `langchain_mcp_adapters` is imported — is created lazily
and imported lazily, so the base install never pulls the optional dependency and the offline test
suite stays green (the capability is OFF by default; tests inject a fake provider).

**Human-in-the-loop on write actions.** A Gmail/Calendar agent *acts on the real world* — sending an
email is irreversible — so its **write** tool calls (send/create/update/delete) sit behind a human
approval gate. `settings.workspace_hitl` selects exactly ONE mechanism so they never double-gate:

  - "primitive"  — this hand-written loop's own batched `interrupt()` gate (path B). The custom
                   `tools` node pauses once with all pending writes, then runs each per the operator's
                   decision (approve / edit args / reject → a synthetic ToolMessage). Mirrors
                   marketing's explicit `interrupt()` — the "show the mechanism" teaching path. Reads
                   (search/list/get) run ungated: the analytics-style "read freely, gate writes".
  - "middleware" — build the agent via `create_agent` + `HumanInTheLoopMiddleware` (path A): the
                   "let the framework do it" contrast. Same `{decisions: [...]}` resume protocol.
  - "off"        — no gate (the original pre-HITL behaviour).

For the pause to actually pause, the orchestrator's `workspace` node must let the `GraphInterrupt`
propagate (it re-raises `GraphBubbleUp` instead of swallowing it under `except Exception`); the
platform/CLI checkpointer + the per-run `config` pass-through carry the pause/resume, exactly as for
marketing's interrupt.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Sequence

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool, ToolException
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from nora.analytics.graph import should_continue  # reuse: "tools" if last.tool_calls else END
from nora.config import Settings, get_settings
from nora.observability import get_logger
from nora.schemas import ApprovalLayout
from nora.state import AnalyticsState

log = get_logger(__name__)

# A callable that mints the operator's Google Workspace tools for one run, given their access token.
# Injectable (the analogue of routing's `route_planner`) so offline tests pass a fake — no MCP server,
# no network. May be sync OR async (the runner awaits it if it returns a coroutine); the default
# implementation is async (it awaits `load_mcp_tools`).
ToolsProvider = Callable[..., Sequence[BaseTool]]

# Predicate: does this tool name MUTATE the operator's account (so a human must approve it)?
WriteToolPredicate = Callable[[str], bool]

WORKSPACE_SYSTEM_PROMPT = (
    "You are Nora, Curry Nomad's operations assistant, acting on the operator's own Google "
    "Workspace account. Use the available tools to carry out the request — send or draft an email, "
    "read or create a calendar event, etc. Only claim an action you actually performed via a tool; "
    "never fabricate a result. When done, reply with a short, plain confirmation of what you did "
    "(who/what/when), or ask one concise clarifying question if the request is ambiguous."
)

# --- the human-approval gate ----------------------------------------------------------

# The interrupt payload's `kind`, so the web client can tell a workspace-write approval apart from the
# marketing concept-pick / script-review gates (and from the middleware path, which carries
# `review_configs`). Both HITL paths resume with the same `{"decisions": [...]}` shape.
WORKSPACE_APPROVAL_KIND = "workspace_approval"

_DEFAULT_REJECT_MESSAGE = (
    "The operator declined this action. Do not retry it unless they ask — you may explain what you "
    "would have done or ask how they'd like to proceed instead."
)

# Tools that mutate the operator's account: a curated set of the real Google Workspace MCP tool names
# (exact match) PLUS a verb fallback, so a renamed/added mutation — or a test's `send_email` fake — is
# still caught. Everything else (search/list/get) is read-only and runs without a pause.
WRITE_TOOL_NAMES = frozenset(
    {
        "send_gmail_message",
        "draft_gmail_message",
        "create_calendar_event",
        "modify_calendar_event",
        "delete_calendar_event",
    }
)
_WRITE_VERBS = (
    "send",
    "create",
    "draft",
    "update",
    "modify",
    "delete",
    "insert",
    "add",
    "remove",
    "move",
    "trash",
)


def is_write_tool(name: str) -> bool:
    """True if a tool call mutates the operator's account (so it needs human approval).

    Exact-match the known write tools first, then fall back to a verb check so an unfamiliar mutation
    (e.g. a server that names its send tool `gmail_send_message`) is still gated. Conservative by
    design: it's safe to gate a borderline read, never safe to miss a write."""
    if name in WRITE_TOOL_NAMES:
        return True
    lowered = name.lower()
    return any(lowered.startswith(verb) or f"_{verb}" in lowered for verb in _WRITE_VERBS)


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

    async def provider(*, access_token: str) -> Sequence[BaseTool]:
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
        # `handle_workspace_error` stays the demonstrated self-correction mechanism (the
        # analytics-contrast teaching point). The node is async now, so we await directly.
        return await load_mcp_tools(None, connection=connection, handle_tool_errors=False)

    return provider


def _make_llm_node(model_with_tools):
    """The shared `llm` node (identical across all three HITL modes) — propose the next tool call(s)
    or the final answer. Async so the loop runs on the orchestrator's event loop (MCP tools are
    coroutine-only)."""

    async def llm_node(state: AnalyticsState) -> dict:
        response = await model_with_tools.ainvoke(
            [SystemMessage(content=WORKSPACE_SYSTEM_PROMPT), *state["messages"]]
        )
        # Same termination guard as analytics (this loop reuses AnalyticsState's `remaining_steps`):
        # if the step budget is nearly spent but the model still wants tools, stop with a plain answer
        # instead of looping into a GraphRecursionError.
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

    return llm_node


def _normalize_decisions(raw, n: int) -> list[dict]:
    """Coerce the resume payload into a per-write list of decision dicts (length `n`, in the same
    order the writes were presented).

    Accepts what real clients actually send: a structured `{"decisions": [...]}` (the canonical
    shape, shared with the middleware path), a JSON *string* of the same, a single decision (or a
    bare `{"approved": bool}`) that's broadcast to every write ("approve all"). A missing decision
    defaults to **reject** — never run a write we didn't get explicit approval for.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = {}

    decisions: list
    if isinstance(raw, dict):
        if isinstance(raw.get("decisions"), list):
            decisions = raw["decisions"]
        elif "approved" in raw:  # a single approve/reject flag for the whole batch
            decisions = [{"type": "approve" if raw["approved"] else "reject"}]
        elif "type" in raw:  # a single decision dict → broadcast
            decisions = [raw]
        else:
            decisions = []
    elif isinstance(raw, list):
        decisions = raw
    else:
        decisions = []

    if len(decisions) == 1 and n > 1:  # one decision means "apply to all" (approve/reject all)
        decisions = decisions * n
    decisions = [d if isinstance(d, dict) else {"type": "approve" if d else "reject"} for d in decisions]
    while len(decisions) < n:  # pad missing with reject (safe default for an unapproved write)
        decisions.append({"type": "reject", "message": _DEFAULT_REJECT_MESSAGE})
    return decisions[:n]


APPROVAL_LAYOUT_INSTRUCTIONS = (
    "You compose a compact APPROVAL CARD for a pending Google Workspace WRITE action that a human is "
    "about to approve before it runs. Choose an `icon` (email / calendar / document / generic), a "
    "short `title` (e.g. 'Send email', 'Draft email', 'Create calendar event'), and an ordered list "
    "of `fields`. Each field has a human `label`, the `arg_key` it reads its value from (use the EXACT "
    "argument keys given — never invent or paraphrase values; the system fills the value), and a "
    "`style`: 'block' for long free text like an email body, 'inline' for short values like a "
    "recipient or subject. Order fields the way a reviewer would want to read them; skip pure "
    "control/formatting args."
)


def _stringify(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, default=str)


async def _author_approval_layout(layout_model, name: str, args: dict) -> dict | None:
    """Best-effort: ask the model to AUTHOR an approval-card layout for one pending write action, then
    resolve each field's value from the LITERAL args — the model only chooses the presentation
    (icon/title/labels/order/which arg goes where), never the values, so the approver always sees
    exactly what will run. Any arg the layout omits is appended, so nothing that will be sent is
    hidden. Returns {icon, title, fields:[{label, value, style}]} or None (→ the web client renders its
    own faithful fallback, e.g. on the middleware path or with no model/key)."""
    if layout_model is None or not isinstance(args, dict) or not args:
        return None
    try:
        context = (
            f"Tool name: {name}\nArgument keys: {list(args.keys())}\n"
            "Compose the card for these keys (values are filled by the system, not you)."
        )
        layout: ApprovalLayout = await layout_model.with_structured_output(ApprovalLayout).ainvoke(
            [SystemMessage(content=APPROVAL_LAYOUT_INSTRUCTIONS), HumanMessage(content=context)]
        )
    except Exception as exc:  # noqa: BLE001 — authoring is best-effort; the UI falls back to a literal card
        log.info("workspace.layout_author_failed", tool=name, error=str(exc))
        return None

    resolved: list[dict] = []
    used: set[str] = set()
    for field in layout.fields:
        if field.arg_key in args:  # literal value, never the model's text
            resolved.append(
                {"label": field.label, "value": _stringify(args[field.arg_key]), "style": field.style}
            )
            used.add(field.arg_key)
    for key, value in args.items():  # nothing that will run is hidden from the approver
        if key not in used:
            resolved.append(
                {
                    "label": key.replace("_", " ").title(),
                    "value": _stringify(value),
                    "style": "block" if len(str(value)) > 80 else "inline",
                }
            )
    return {"icon": layout.icon, "title": layout.title, "fields": resolved}


def _make_gated_tools_node(
    tools: Sequence[BaseTool], is_write: WriteToolPredicate, layout_model=None
):
    """The custom `tools` node for the "primitive" HITL mode: a hand-rolled ToolNode that pauses on
    write actions.

    It calls `interrupt()` **exactly once** per turn, batching every pending write so resume is a
    single `{"decisions": [...]}` value (no keyed-multi-interrupt protocol). Reads run ungated. Then
    it executes each call per its decision, reusing `handle_workspace_error` for the narrow,
    self-correcting ToolException path (the analytics-contrast teaching point) and delegating result
    wrapping to LangChain by invoking each tool with its full tool-call dict (so artifacts survive)."""
    tools_by_name = {t.name: t for t in tools}

    async def gated_tools(state: AnalyticsState) -> dict:
        last = state["messages"][-1]
        calls = list(getattr(last, "tool_calls", None) or [])
        writes = [c for c in calls if is_write(c["name"])]

        decision_by_id: dict[str, dict] = {}
        if writes:
            log.info("hitl.raised", question="approve workspace writes",
                     actions=[c["name"] for c in writes])
            action_requests = []
            for c in writes:
                request = {
                    "name": c["name"],
                    "args": c["args"],
                    "id": c["id"],
                    "description": f"{c['name']}({json.dumps(c['args'], default=str)})",
                }
                # AI-author a polished approval layout (presentation only; values stay literal). Rides
                # in the interrupt payload because the interrupt halts the node — there's no
                # push_ui_message hook for it. Best-effort: None → the web client's literal fallback.
                layout = await _author_approval_layout(layout_model, c["name"], c["args"])
                if layout is not None:
                    request["layout"] = layout
                action_requests.append(request)
            raw = interrupt(
                {
                    "kind": WORKSPACE_APPROVAL_KIND,
                    "question": "Approve these Google Workspace actions before Nora runs them?",
                    "action_requests": action_requests,
                }
            )
            decisions = _normalize_decisions(raw, len(writes))  # exactly one per write, in order
            decision_by_id = {c["id"]: d for c, d in zip(writes, decisions, strict=True)}

        out: list[BaseMessage] = []
        for call in calls:
            name, args, call_id = call["name"], call["args"], call["id"]
            decision = decision_by_id.get(call_id)
            if decision is not None:
                dtype = decision.get("type", "approve")
                if dtype == "reject":
                    log.info("workspace.write_rejected", tool=name)
                    out.append(
                        ToolMessage(
                            content=decision.get("message") or _DEFAULT_REJECT_MESSAGE,
                            tool_call_id=call_id,
                            name=name,
                        )
                    )
                    continue
                if dtype == "edit":  # honor edited args (the middleware's `edited_action` shape too)
                    edited = decision.get("edited_action") or {}
                    args = edited.get("args", decision.get("args", args))
                    log.info("workspace.write_edited", tool=name)
                else:
                    log.info("workspace.write_approved", tool=name)

            tool = tools_by_name.get(name)
            if tool is None:  # the model hallucinated a tool name — feed it back to self-correct
                out.append(ToolMessage(content=f"Unknown tool: {name}", tool_call_id=call_id, name=name))
                continue
            # Invoke with the full tool-call dict so LangChain returns a ToolMessage (handling
            # content-and-artifact results); MCP tools (minted with handle_tool_errors=False) RAISE a
            # ToolException, which our narrow handler turns into a self-correction ToolMessage.
            tool_call = {"name": name, "args": args, "id": call_id, "type": "tool_call"}
            try:
                out.append(await tool.ainvoke(tool_call))
            except ToolException as exc:
                out.append(ToolMessage(content=handle_workspace_error(exc), tool_call_id=call_id, name=name))
        return {"messages": out}

    return gated_tools


# --- compile paths (one per HITL mode) ------------------------------------------------


def _compile_loop(model, tools: Sequence[BaseTool]):
    """The ungated loop ("off"): the original llm↔ToolNode loop, writes run straight through."""
    builder = StateGraph(AnalyticsState)
    builder.add_node("llm", _make_llm_node(model.bind_tools(tools)))
    builder.add_node("tools", ToolNode(tools, handle_tool_errors=handle_workspace_error))
    builder.add_edge(START, "llm")
    builder.add_conditional_edges("llm", should_continue, ["tools", END])
    builder.add_edge("tools", "llm")
    return builder.compile()


def _compile_loop_gated(
    model, tools: Sequence[BaseTool], is_write: WriteToolPredicate, layout_model=None
):
    """The "primitive" loop (path B): same shape, but the `tools` node is the hand-rolled gate that
    pauses on write actions via `interrupt()` (and AI-authors the approval card via `layout_model`)."""
    builder = StateGraph(AnalyticsState)
    builder.add_node("llm", _make_llm_node(model.bind_tools(tools)))
    builder.add_node("tools", _make_gated_tools_node(tools, is_write, layout_model))
    builder.add_edge(START, "llm")
    builder.add_conditional_edges("llm", should_continue, ["tools", END])
    builder.add_edge("tools", "llm")
    return builder.compile()


def _self_correcting(tool: BaseTool) -> BaseTool:
    """Wrap a tool so a recoverable `ToolException` comes back as the curated self-correction
    ToolMessage *content* instead of raising.

    `create_agent` + `HumanInTheLoopMiddleware` execute an approved tool directly and let a
    `ToolException` propagate — which would escape the agent and degrade the whole turn (it can't
    self-correct). The hand-written loop avoids that with `handle_workspace_error` in its ToolNode;
    this restores the SAME behaviour on the middleware path by turning the raise into normal tool
    output the model reads and repairs from. Mirrors `analytics.handle_sql_error` — still narrow
    (only `ToolException`); anything else (transport/auth) propagates and fails loud."""

    async def gated(**kwargs):
        try:
            return await tool.ainvoke(kwargs)
        except ToolException as exc:
            return handle_workspace_error(exc)

    return StructuredTool.from_function(
        coroutine=gated,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
    )


def _compile_middleware_agent(model, tools: Sequence[BaseTool], is_write: WriteToolPredicate):
    """The "middleware" agent (path A, the DEFAULT): the prebuilt `create_agent` with
    `HumanInTheLoopMiddleware` gating the write tools. The contrast with path B — the framework's
    after-model hook raises the interrupt and applies the decisions, instead of the hand-written gate
    node. Same outward interface (`ainvoke({"messages": ...}, config) -> {"messages": [...]}`) and the
    same `{"decisions": [...]}` resume protocol, so the orchestrator node and the web client don't
    care which mode is active.

    Tools are wrapped with `_self_correcting` so a recoverable `ToolException` still becomes a
    ToolMessage the model repairs (the prebuilt agent doesn't do this on its own) — keeping the
    self-correcting tool loop that the hand-written path has natively."""
    from langchain.agents import create_agent
    from langchain.agents.middleware import HumanInTheLoopMiddleware

    tools = [_self_correcting(t) for t in tools]
    interrupt_on = {t.name: True for t in tools if is_write(t.name)}
    return create_agent(
        model=model,
        tools=list(tools),
        system_prompt=WORKSPACE_SYSTEM_PROMPT,
        middleware=[
            HumanInTheLoopMiddleware(
                interrupt_on=interrupt_on,
                description_prefix="Workspace action pending approval",
            )
        ],
    )


def build_workspace_agent(
    *,
    settings: Settings | None = None,
    model=None,
    tools_provider: ToolsProvider | None = None,
    hitl: str | None = None,
    is_write: WriteToolPredicate | None = None,
    layout_model=None,
):
    """Build the workspace capability runner.

    Returns an **async** callable `arun(messages, *, access_token, config=None) -> list[BaseMessage]`
    that binds the operator's per-run MCP tools, runs the tool loop, and returns ONLY the new
    messages (the tool-call steps + final answer) so they merge into the top-level thread and render
    inline (the model streams, like analytics — its tokens are the answer).

    `model` and `tools_provider` are injectable for offline tests (a `ScriptedChatModel` + a fake
    tool list); by default the model is built from settings (lazily, so building the agent needs no
    provider key) and the tools come from the real (async) MCP client provider. `hitl` selects the
    approval mechanism (defaults to `settings.workspace_hitl`); `is_write` overrides the write-tool
    predicate (injectable so tests can gate a custom fake tool name). `layout_model` (the "primitive"
    path only) AI-authors the approval card; None disables authoring (the web client falls back to a
    literal card), so offline tests need no key.
    """
    settings = settings or get_settings()
    provider = tools_provider or _make_mcp_tools_provider(settings)
    mode = hitl if hitl is not None else settings.workspace_hitl
    write_pred = is_write or is_write_tool
    _model = model  # may be None → built lazily on first run (so flag-on build needs no key at import)

    async def arun(messages: list, *, access_token: str, config=None) -> list[BaseMessage]:
        nonlocal _model
        if _model is None:
            _model = init_chat_model(settings.model, temperature=0, streaming=True)
        # The provider may be sync (a test fake returning a list) or async (the real one, which
        # awaits load_mcp_tools) — await it only if it handed back a coroutine.
        tools = provider(access_token=access_token)
        if inspect.isawaitable(tools):
            tools = await tools
        # Compile the loop for THIS run's tool set + HITL mode. Recompiled per run (the tool set is
        # per-operator); resume works through the recompile because LangGraph keys subgraph
        # checkpoints on the node-name/structural path, not object identity, and we forward `config`.
        if mode == "middleware":
            agent = _compile_middleware_agent(_model, tools, write_pred)
        elif mode == "primitive":
            agent = _compile_loop_gated(_model, tools, write_pred, layout_model)
        else:
            agent = _compile_loop(_model, tools)
        # Drive the loop async: MCP tools are coroutine-only, and the orchestrator is already on the
        # event loop (Aegra `astream`, the CLI `astream`), so we await directly — no `asyncio.run`.
        result = await agent.ainvoke({"messages": messages}, config)
        # Return only the tail the agent appended (add_messages keeps input messages at the front by
        # id), so we don't re-emit the operator's prompt into the top-level thread.
        return list(result["messages"][len(messages) :])

    return arun
