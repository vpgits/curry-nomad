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
and imported lazily. `langchain_mcp_adapters` is a base dependency now, so the capability defaults ON
(`settings.workspace_enabled = True`); the offline test suite stays green because conftest pins it
OFF and tests inject a fake provider rather than minting a real MCP client.

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
from typing import Annotated

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool, ToolException
from langgraph.graph import END, START, StateGraph
from langgraph.graph.ui import AnyUIMessage, ui_message_reducer
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from nora.analytics.graph import should_continue  # reuse: "tools" if last.tool_calls else END
from nora.config import Settings, get_settings
from nora.observability import get_logger
from nora.runtime_context import runtime_context_block
from nora.schemas import ApprovalLayout
from nora.state import AnalyticsState
from nora.ui_tools import present_ui

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
    "Workspace account. Use the available tools to carry out the request — for example create or "
    "edit a Google Sheet (build a spreadsheet, add tabs, write values), edit a Google Doc, manage "
    "Google Tasks, search Google Drive, or draft/send an email. Only claim an action you actually "
    "performed via a tool; never fabricate a result. When done, reply with a short, plain "
    "confirmation of what you did (who/what/when), or ask one concise clarifying question if the "
    "request is ambiguous."
)


def _workspace_system_prompt(settings: Settings) -> str:
    """The workspace agent's system prompt with its available Google tools spelled out from the
    granted scopes (`settings.workspace_scope_summary()`), so what the agent believes it can do is
    derived from the real grant — not a hand-written list that drifts. Falls back to the static
    WORKSPACE_SYSTEM_PROMPT shape but with the concrete scope line prepended."""
    return (
        "You are Nora, Curry Nomad's operations assistant, acting on the operator's own Google "
        f"Workspace account. Your available Google tools cover: {settings.workspace_scope_summary()}. "
        "The supervisor has delegated this to you — you may see a `to_workspace` handoff call and a "
        "'Handing off to workspace.' note in the history. THAT is your assignment; carry it out with "
        "your tools. Do NOT reply that you can't do it, or that you lack a tool, before you have "
        "actually tried — inspect the available tools and call the right one (a calendar action uses "
        "the event tool, an email uses the Gmail tool, and so on). "
        "Use them to carry out the request — for example create or edit a Google Sheet (build a "
        "spreadsheet, add tabs, write values), edit a Doc, manage Tasks, search Drive, or draft/send "
        "an email. Only claim an action you actually performed via a tool; never fabricate a result. "
        "Use your judgment about showing a result as an inline card with present_ui: when you've "
        "created or found something worth showing — a calendar event, an email, a task, a doc, a "
        "spreadsheet, or a list of items — render it ALONGSIDE your written confirmation: a `fields` "
        "card for one thing's details (e.g. Title / When / Where / Attendees for an event), a `table` "
        "for several items, `metrics` tiles for a few numbers. Skip the card for a trivial reply, a "
        "bare yes/no, or a clarifying question — just answer in words. When done, reply with a short, "
        "plain confirmation of what you did, or ask one concise clarifying question if the request is "
        "ambiguous."
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

# Tools that mutate the operator's account: a curated set of real Google Workspace MCP tool names
# (exact match) PLUS a verb fallback, so a renamed/added mutation — or a test's `send_email` fake — is
# still caught. Everything else (search/list/get) is read-only and runs without a pause.
# Exact names here are belt-and-suspenders over the verb fallback, plus the ONE write no verb catches:
# `export_doc_to_pdf` reads like a getter but writes a new PDF file to Drive. (`send_gmail_message` /
# `draft_gmail_message` / `manage_event` are also verb-caught — listed for clarity.)
WRITE_TOOL_NAMES = frozenset(
    {
        "send_gmail_message",
        "draft_gmail_message",
        "manage_event",  # the real calendar create/modify/delete tool (was miswritten as *_calendar_event)
        "export_doc_to_pdf",
    }
)
_WRITE_VERBS = (
    "send",
    "create",
    "draft",
    "update",
    # This MCP server names its multi-mode create/update/delete tools `manage_*` (manage_event,
    # manage_task, manage_task_list, manage_gmail_label, manage_out_of_office, manage_focus_time,
    # manage_drive_access, manage_doc_tab, manage_conditional_formatting, …). Without "manage" the
    # verb fallback missed ALL of them and they ran with NO approval gate — the audited bypass class.
    # Verified against the full 71-tool surface: no READ tool starts with / contains `_manage`.
    "manage",
    "modify",
    "delete",
    "insert",
    "add",
    "remove",
    "move",
    "trash",
    # Docs/Sheets/Tasks/Drive mutations the granted scopes (docs:full sheets:full tasks:full) expose
    # but the Gmail/Calendar-shaped verbs above miss — e.g. replace_text, append_values, clear_values,
    # batch_update, complete_task, rename_/share_/copy_/upload_, format_sheet_range,
    # resize_sheet_dimensions. Over-gating a read is safe; missing a write is not, so keep this list
    # generous. ("format"/"resize" match no READ tool in the enumerated surface.)
    "replace",
    "append",
    "clear",
    "complete",
    "batch",
    "rename",
    "share",
    "copy",
    "upload",
    "import",
    "write",
    "set",
    "patch",
    "put",
    "format",
    "resize",
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


def _make_llm_node(model_with_tools, system_prompt: str = WORKSPACE_SYSTEM_PROMPT):
    """The shared `llm` node (identical across all three HITL modes) — propose the next tool call(s)
    or the final answer. Async so the loop runs on the orchestrator's event loop (MCP tools are
    coroutine-only). `system_prompt` defaults to the base prompt but the orchestrator passes it
    augmented with recalled memory (see `build_workspace_agent.arun`)."""

    async def llm_node(state: AnalyticsState) -> dict:
        response = await model_with_tools.ainvoke(
            [SystemMessage(content=system_prompt), *state["messages"]]
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
    "about to approve before it runs. Choose an `icon` (email / calendar / document / generic — use "
    "'document' for Sheets/Docs/Drive/Tasks actions), a short `title` (e.g. 'Send email', 'Create "
    "spreadsheet', 'Update spreadsheet', 'Edit doc', 'Add task'), and an ordered list "
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
                            # Tag so the orchestrator's "workspace_actions" badge skips declined writes.
                            additional_kwargs={"workspace_decision": "reject"},
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


def _compile_loop(model, tools: Sequence[BaseTool], system_prompt: str = WORKSPACE_SYSTEM_PROMPT):
    """The ungated loop ("off"): the original llm↔ToolNode loop, writes run straight through."""
    builder = StateGraph(AnalyticsState)
    builder.add_node("llm", _make_llm_node(model.bind_tools(tools), system_prompt))
    builder.add_node("tools", ToolNode(tools, handle_tool_errors=handle_workspace_error))
    builder.add_edge(START, "llm")
    builder.add_conditional_edges("llm", should_continue, ["tools", END])
    builder.add_edge("tools", "llm")
    return builder.compile()


def _compile_loop_gated(
    model,
    tools: Sequence[BaseTool],
    is_write: WriteToolPredicate,
    layout_model=None,
    system_prompt: str = WORKSPACE_SYSTEM_PROMPT,
):
    """The "primitive" loop (path B): same shape, but the `tools` node is the hand-rolled gate that
    pauses on write actions via `interrupt()` (and AI-authors the approval card via `layout_model`)."""
    builder = StateGraph(AnalyticsState)
    builder.add_node("llm", _make_llm_node(model.bind_tools(tools), system_prompt))
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
            # `tool.ainvoke(args)` already UNWRAPS a content_and_artifact tool down to its content
            # (a list of content blocks), so the wrapper below MUST declare response_format="content".
            # Declaring content_and_artifact (copied from the MCP tool) made LangChain expect a
            # 2-tuple back from `gated` and raise "Since response_format='content_and_artifact' a
            # two-tuple ... is expected. Instead ... list." on the FIRST approved write (e.g.
            # create_spreadsheet). That ValueError then bubbled up and got mislabeled as an approval
            # mismatch. The raw artifact isn't consumed downstream here — the model reads the content.
            return await tool.ainvoke(kwargs)
        except ToolException as exc:
            return handle_workspace_error(exc)

    return StructuredTool.from_function(
        coroutine=gated,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        # Carry the original tool's metadata/tags/return_direct forward so re-wrapping doesn't
        # silently drop them.
        metadata=getattr(tool, "metadata", None),
        tags=getattr(tool, "tags", None),
        return_direct=getattr(tool, "return_direct", False),
        # `gated` returns already-unwrapped content (or a self-correction string), never a 2-tuple.
        response_format="content",
    )


def _compile_middleware_agent(
    model,
    tools: Sequence[BaseTool],
    is_write: WriteToolPredicate,
    system_prompt: str = WORKSPACE_SYSTEM_PROMPT,
):
    """The "middleware" agent (path A, the DEFAULT): the prebuilt `create_agent` with
    `HumanInTheLoopMiddleware` gating the write tools. The contrast with path B — the framework's
    after-model hook raises the interrupt and applies the decisions, instead of the hand-written gate
    node. Same outward interface (`ainvoke({"messages": ...}, config) -> {"messages": [...]}`) and the
    same `{"decisions": [...]}` resume protocol, so the orchestrator node and the web client don't
    care which mode is active.

    Tools are wrapped with `_self_correcting` so a recoverable `ToolException` still becomes a
    ToolMessage the model repairs (the prebuilt agent doesn't do this on its own) — keeping the
    self-correcting tool loop that the hand-written path has natively. The local `present_ui` tool is
    the ONE exception: it's left UNWRAPPED because the shim copies args_schema + forces
    response_format='content', which strips its `InjectedState` injection — and it can't raise a
    ToolException anyway (it's a best-effort local UI push). A custom `state_schema` gives it a real
    `ui` channel so its inline card write doesn't hit an undeclared-channel warning."""
    from langchain.agents import create_agent
    from langchain.agents.middleware import AgentState, HumanInTheLoopMiddleware

    class _NameGuardedHITL(HumanInTheLoopMiddleware):
        """Defense-in-depth over `HumanInTheLoopMiddleware`: an `edit` decision may change a pending
        write's ARGS but NEVER its tool NAME. The base `_process_decision` honors `edited_action['name']`
        verbatim and reuses the original tool-call id (so no second interrupt fires), which lets a
        crafted resume swap the reviewed `send_gmail_message` for a never-shown `manage_event(delete)`.
        We clamp the edited name back to the tool the human actually saw before the base handles it.
        (`after_model`/`aafter_model` both call `self._process_decision`, so this one override covers
        the sync and async paths; the hand-written 'primitive' gate is already safe — it reads only
        `edited_action['args']`, never the name.)"""

        @staticmethod
        def _process_decision(decision, tool_call, config):
            if isinstance(decision, dict) and decision.get("type") == "edit":
                edited = decision.get("edited_action")
                if isinstance(edited, dict) and edited.get("name") != tool_call["name"]:
                    log.info(
                        "workspace.edit_name_clamped",
                        reviewed=tool_call["name"],
                        attempted=edited.get("name"),
                    )
                    decision = {**decision, "edited_action": {**edited, "name": tool_call["name"]}}
            return HumanInTheLoopMiddleware._process_decision(decision, tool_call, config)

    wrapped = [t if t.name == present_ui.name else _self_correcting(t) for t in tools]
    # Explicit allowed_decisions (approve / edit args / reject) — drop the unused "respond" (human
    # answers on behalf of the tool), which we never surface. The name-swap is closed by the clamp above.
    interrupt_on = {
        t.name: {"allowed_decisions": ["approve", "edit", "reject"]}
        for t in wrapped
        if is_write(t.name)
    }

    class _WorkspaceMiddlewareState(AgentState):
        # Mirror the orchestrator's channel so present_ui's card lands somewhere real; the surface is
        # re-emitted at the orchestrator level regardless (this loop's state is discarded), so this is
        # purely to keep the middleware path warning-clean.
        ui: Annotated[Sequence[AnyUIMessage], ui_message_reducer]

    return create_agent(
        model=model,
        tools=list(wrapped),
        system_prompt=system_prompt,
        state_schema=_WorkspaceMiddlewareState,
        middleware=[
            _NameGuardedHITL(
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

    async def arun(
        messages: list, *, access_token: str, config=None, memory_context: str = ""
    ) -> list[BaseMessage]:
        nonlocal _model
        if _model is None:
            _model = init_chat_model(settings.model_for("workspace"), temperature=0, streaming=True)
        # The provider may be sync (a test fake returning a list) or async (the real one, which
        # awaits load_mcp_tools) — await it only if it handed back a coroutine.
        tools = provider(access_token=access_token)
        if inspect.isawaitable(tools):
            tools = await tools
        # Add the generative-UI authoring tool so the workspace agent can render a table/metrics/chart
        # card inline (e.g. a table of matched emails). It's a read-like local tool (never gated), and
        # the orchestrator's workspace node re-emits whatever surfaces it authored — see
        # `ui_tools.emit_present_ui_from_messages` (this imperative loop's `ui` channel is discarded).
        tools = [*tools, present_ui]
        # Base prompt is derived from the granted scopes (so the agent knows its real Sheets/Docs/
        # Drive/Tasks reach), then folded with any recalled long-term memory the orchestrator computed
        # from the runtime store, then the live runtime context (current date + operator timezone) so
        # a calendar/date request resolves without asking "which timezone is 'today 5pm'?". Both are
        # appended AFTER the static base prompt so the cacheable prefix stays stable. Empty → unchanged.
        base_prompt = _workspace_system_prompt(settings)
        runtime_context = runtime_context_block(config)
        system_prompt = (
            base_prompt
            + (f"\n\n{memory_context}" if memory_context else "")
            + (f"\n\n{runtime_context}" if runtime_context else "")
        )
        # Compile the loop for THIS run's tool set + HITL mode. Recompiled per run (the tool set is
        # per-operator); resume works through the recompile because LangGraph keys subgraph
        # checkpoints on the node-name/structural path, not object identity, and we forward `config`.
        if mode == "middleware":
            agent = _compile_middleware_agent(_model, tools, write_pred, system_prompt)
        elif mode == "primitive":
            agent = _compile_loop_gated(_model, tools, write_pred, layout_model, system_prompt)
        elif mode == "off":
            # Explicit opt-OUT only → the ungated loop. Fail-closed: an UNRECOGNIZED mode (a typo, an
            # empty string, a not-yet-wired name) must NOT silently fall through to "no gate" — that
            # would disable write approval account-wide without a peep. Raise instead. (`settings.
            # workspace_hitl` is a validated Literal, so this only guards the injectable `hitl=` param.)
            agent = _compile_loop(_model, tools, system_prompt)
        else:
            raise ValueError(
                f"unknown workspace_hitl mode {mode!r}; expected 'middleware', 'primitive', or 'off'"
            )
        # Drive the loop async: MCP tools are coroutine-only, and the orchestrator is already on the
        # event loop (Aegra `astream`, the CLI `astream`), so we await directly — no `asyncio.run`.
        result = await agent.ainvoke({"messages": messages}, config)
        # Return only the tail the agent appended (add_messages keeps input messages at the front by
        # id), so we don't re-emit the operator's prompt into the top-level thread.
        return list(result["messages"][len(messages) :])

    return arun
