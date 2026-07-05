"""The operations agent — Phase 2 of the operations subsystem.

An LLM tool-loop that CRUDs orders, stock, and customers by **calling the deterministic
``operations/services.py``**, not by reasoning about the rules itself. It fuses the two patterns the
repo already proves:

- **analytics** — a hand-written ``llm ↔ tools`` loop that self-corrects: a rejected request raises
  ``OperationsError`` (the deliberate twin of ``SqlError``), which becomes a ToolMessage the model
  reads and repairs from. The rules live in the service, so the agent literally cannot break them.
- **workspace** — a write-approval **HITL** gate: a hand-rolled tools node that calls ``interrupt()``
  once (batched) for the pending HIGH-RISK writes and resumes with ``Command(resume={"decisions":…}))``.

It reuses ``AnalyticsState`` (messages + ``remaining_steps`` + the shared ``ui`` channel) and the
analytics ``should_continue`` router. It's compiled fresh per run and driven imperatively by the
orchestrator's ``operations`` node (sync ``.invoke(state, config)``, so a deep ``interrupt()`` bubbles
up and a resume flows back down — like ``marketing``).
"""

from __future__ import annotations

import json
from collections.abc import Callable

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from nora.analytics.graph import should_continue  # reuse: "tools" if last.tool_calls else END
from nora.config import Settings, get_settings
from nora.memory import MEMORY_TOOLS
from nora.observability import get_logger
from nora.operations.agent_tools import WRITE_TOOL_NAMES, make_operations_tools
from nora.operations.errors import OperationsError
from nora.operations.store import build_operations_store
from nora.runtime_context import runtime_context_block
from nora.schemas import ApprovalLayout
from nora.state import AnalyticsState
from nora.ui_tools import present_ui

log = get_logger(__name__)

# The interrupt payload's `kind`, so the web client can tell an operations write-approval apart from
# the marketing gates. It carries an `action_requests` array, so the web's `isWorkspaceApproval`
# discriminator (structural — "has action_requests") already routes it to the shared approval card.
OPERATIONS_APPROVAL_KIND = "operations_approval"
_DEFAULT_REJECT_MESSAGE = "The operator declined this action."

RiskPredicate = Callable[[str, dict], bool]

# High-risk = irreversible or destructive → gate for human approval. Everything else (create_order,
# receive_stock, create/update_customer, and all reads) runs straight through under the default policy.
_HIGH_RISK_NAMES = frozenset({"cancel_order", "edit_order", "delete_customer"})


def is_high_risk_op(name: str, args: dict) -> bool:
    """Args-aware risk predicate (the operations analogue of workspace's name-only ``is_write_tool``):
    cancel/edit an order and delete a customer are always high-risk; a stock ``adjust`` is high-risk
    only when it's a write-off or a *negative* correction (it destroys inventory)."""
    if name in _HIGH_RISK_NAMES:
        return True
    if name == "adjust_stock":
        qty = args.get("qty_delta")
        return args.get("kind") == "write_off" or (isinstance(qty, int) and qty < 0)
    return False


def _risk_predicate(policy: str) -> RiskPredicate:
    """Select the gate policy: 'off' (gate nothing), 'all' (gate every write), or 'high_risk' (the
    default — only irreversible/destructive writes)."""
    if policy == "off":
        return lambda name, args: False
    if policy == "all":
        return lambda name, args: name in WRITE_TOOL_NAMES
    return is_high_risk_op


def handle_operations_error(error: OperationsError) -> str:
    """Turn a business-rule rejection into a self-correction ToolMessage — the twin of analytics'
    ``handle_sql_error``. The narrow first-param annotation is load-bearing: only ``OperationsError``
    is caught; any other exception propagates and fails loud."""
    log.info("ops.error", error=str(error))
    return (
        f"That operation was rejected: {error}\n"
        "Read the reason, correct the request, and try again — or, if it genuinely can't be done, "
        "explain the blocker to the operator instead of retrying blindly."
    )


OPERATIONS_SYSTEM_PROMPT = (
    "You are Nora, Curry Nomad's operations assistant. You manage the business's ORDERS, STOCK, and "
    "CUSTOMERS by calling your tools — never by guessing or narrating. "
    "The supervisor has delegated this to you — you may see a `to_operations` handoff call and a "
    "'Handing off to operations.' note in the history. THAT is your assignment; carry it out with your "
    "tools. Do NOT reply that you can't do it before you have actually tried — inspect your tools and "
    "call the right one. "
    "Every business rule (no overselling, stock can't go negative or below what's reserved, a customer "
    "with orders can't be deleted) is enforced by the tools, NOT by you. If a tool returns an error, "
    "read it, fix the request, and retry; only give up when it truly can't be satisfied. "
    "When you need an id you don't have, look it up first (list_customers / list_stock / list_orders) "
    "rather than guessing. "
    "Some actions (cancelling or editing an order, deleting a customer, writing off stock) pause for "
    "the operator's approval before they run — that's expected: propose the action and let the approval "
    "happen. "
    "Use present_ui to show a result as an inline card when it reads better visually — a created order "
    "or customer as a `fields` card, a stock/orders list as a `table`, a few headline numbers as "
    "`metrics` — ALONGSIDE a brief written confirmation; skip the card for a trivial reply or a "
    "clarifying question. "
    "When done, reply with a short, plain confirmation of what you did."
)


def _make_llm_node(model_with_tools, system_prompt: str):
    """Propose the next tool call(s) or the final answer. Same ``remaining_steps`` termination guard as
    analytics/workspace (this loop reuses ``AnalyticsState``): near the step budget, stop with a plain
    answer instead of looping into a ``GraphRecursionError`` that would crash the whole turn."""

    def llm_node(state: AnalyticsState) -> dict:
        response = model_with_tools.invoke([SystemMessage(content=system_prompt), *state["messages"]])
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
    """Coerce the resume payload into one decision dict per gated write, in order. Accepts the
    canonical ``{"decisions": [...]}``, a JSON string of it, or a single decision / ``{"approved": bool}``
    broadcast to all. A missing decision defaults to **reject** — never run an unapproved write."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = {}

    decisions: list
    if isinstance(raw, dict):
        if isinstance(raw.get("decisions"), list):
            decisions = raw["decisions"]
        elif "approved" in raw:
            decisions = [{"type": "approve" if raw["approved"] else "reject"}]
        elif "type" in raw:
            decisions = [raw]
        else:
            decisions = []
    elif isinstance(raw, list):
        decisions = raw
    else:
        decisions = []

    if len(decisions) == 1 and n > 1:  # one decision means "apply to all"
        decisions = decisions * n
    decisions = [d if isinstance(d, dict) else {"type": "approve" if d else "reject"} for d in decisions]
    while len(decisions) < n:
        decisions.append({"type": "reject", "message": _DEFAULT_REJECT_MESSAGE})
    return decisions[:n]


def _stringify(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, default=str)


def _author_approval_layout(layout_model, name: str, args: dict) -> dict | None:
    """Best-effort: ask the model to AUTHOR the approval card's presentation (icon/title/field order),
    with every value filled from the LITERAL args by code — so the approver always sees exactly what
    will run. Any omitted arg is appended (nothing that will run is hidden). None → the web client
    renders its own faithful fallback (e.g. no ``layout_model``/key)."""
    if layout_model is None or not isinstance(args, dict) or not args:
        return None
    try:
        context = (
            f"Tool name: {name}\nArgument keys: {list(args.keys())}\n"
            "Compose the card for these keys (values are filled by the system, not you)."
        )
        layout: ApprovalLayout = layout_model.with_structured_output(ApprovalLayout).invoke(
            [SystemMessage(content=OPERATIONS_LAYOUT_INSTRUCTIONS), HumanMessage(content=context)]
        )
    except Exception as exc:  # noqa: BLE001 — authoring is best-effort; the UI falls back to a literal card
        log.info("ops.layout_author_failed", tool=name, error=str(exc))
        return None

    resolved: list[dict] = []
    used: set[str] = set()
    for field in layout.fields:
        if field.arg_key in args:
            resolved.append(
                {"label": field.label, "value": _stringify(args[field.arg_key]), "style": field.style}
            )
            used.add(field.arg_key)
    for key, value in args.items():
        if key not in used:
            resolved.append(
                {
                    "label": key.replace("_", " ").title(),
                    "value": _stringify(value),
                    "style": "block" if len(str(value)) > 80 else "inline",
                }
            )
    return {"icon": layout.icon, "title": layout.title, "fields": resolved}


OPERATIONS_LAYOUT_INSTRUCTIONS = (
    "You compose a compact APPROVAL CARD for a pending operations WRITE that a human is about to "
    "approve before it runs (cancel/edit an order, delete a customer, or write off stock). Choose an "
    "`icon` (use 'generic' for stock/orders, 'document' for a customer record), a short `title` (e.g. "
    "'Cancel order', 'Edit order', 'Write off stock', 'Delete customer'), and an ordered list of "
    "`fields`. Each field has a human `label`, the `arg_key` it reads its value from (use the EXACT "
    "argument keys given — never invent or paraphrase values; the system fills the value), and a "
    "`style`: 'block' for long text, 'inline' for short values like an id or quantity. Order fields "
    "the way a reviewer would read them."
)


def _make_gated_tools_node(tools, is_high_risk: RiskPredicate, layout_model=None):
    """The hand-rolled tools node: run every tool call, but pause the HIGH-RISK writes for approval.

    It calls ``interrupt()`` **once**, batching all pending high-risk writes into a single
    ``action_requests`` payload (resume is one ``{"decisions": [...]}`` value). Reads and low-risk
    writes run straight through. Every tool invocation is wrapped so an ``OperationsError`` becomes a
    self-correction ToolMessage (the analytics-contrast teaching point)."""
    tools_by_name = {t.name: t for t in tools}

    def gated_tools(state: AnalyticsState) -> dict:
        last = state["messages"][-1]
        calls = list(getattr(last, "tool_calls", None) or [])
        gated = [c for c in calls if is_high_risk(c["name"], c.get("args") or {})]

        decision_by_id: dict[str, dict] = {}
        if gated:
            log.info("hitl.raised", question="approve operations writes", actions=[c["name"] for c in gated])
            action_requests = []
            for c in gated:
                request = {
                    "name": c["name"],
                    "args": c["args"],
                    "id": c["id"],
                    "description": f"{c['name']}({json.dumps(c['args'], default=str)})",
                }
                layout = _author_approval_layout(layout_model, c["name"], c["args"])
                if layout is not None:
                    request["layout"] = layout
                action_requests.append(request)
            raw = interrupt(
                {
                    "kind": OPERATIONS_APPROVAL_KIND,
                    "question": "Approve these operations before Nora runs them?",
                    "action_requests": action_requests,
                }
            )
            decisions = _normalize_decisions(raw, len(gated))
            decision_by_id = {c["id"]: d for c, d in zip(gated, decisions, strict=True)}

        out: list[BaseMessage] = []
        for call in calls:
            name, args, call_id = call["name"], call["args"], call["id"]
            decision = decision_by_id.get(call_id)
            if decision is not None:
                dtype = decision.get("type", "approve")
                if dtype == "reject":
                    log.info("ops.write_rejected", tool=name)
                    out.append(
                        ToolMessage(
                            content=decision.get("message") or _DEFAULT_REJECT_MESSAGE,
                            tool_call_id=call_id,
                            name=name,
                            # Tag so the orchestrator's "ops_actions" badge skips declined writes.
                            additional_kwargs={"operations_decision": "reject"},
                        )
                    )
                    continue
                if dtype == "edit":  # honor edited args
                    edited = decision.get("edited_action") or {}
                    args = edited.get("args", decision.get("args", args))
                    log.info("ops.write_edited", tool=name)
                else:
                    log.info("ops.write_approved", tool=name)

            tool = tools_by_name.get(name)
            if tool is None:  # hallucinated tool name → feed it back to self-correct
                out.append(ToolMessage(content=f"Unknown tool: {name}", tool_call_id=call_id, name=name))
                continue
            tool_call = {"name": name, "args": args, "id": call_id, "type": "tool_call"}
            try:
                out.append(tool.invoke(tool_call))
            except OperationsError as exc:  # the ONLY caught error — the self-correction seam
                out.append(ToolMessage(content=handle_operations_error(exc), tool_call_id=call_id, name=name))
        return {"messages": out}

    return gated_tools


def _compile(model, tools, is_high_risk: RiskPredicate, layout_model, system_prompt: str):
    builder = StateGraph(AnalyticsState)
    builder.add_node("llm", _make_llm_node(model.bind_tools(tools), system_prompt))
    builder.add_node("tools", _make_gated_tools_node(tools, is_high_risk, layout_model))
    builder.add_edge(START, "llm")
    builder.add_conditional_edges("llm", should_continue, ["tools", END])
    builder.add_edge("tools", "llm")
    return builder.compile()  # no checkpointer — the parent orchestrator's drives HITL via config


def build_operations_agent(
    *,
    settings: Settings | None = None,
    model=None,
    store=None,
    is_high_risk: RiskPredicate | None = None,
    layout_model=None,
):
    """Build the operations capability runner.

    Returns a **sync** callable ``run(messages, *, config=None, memory_context="") ->
    list[BaseMessage]`` that binds the CRUD tools to the writable store, runs the loop, and returns
    ONLY the appended messages (so they merge into the top-level thread). ``model`` and ``store`` are
    injectable for offline tests (a ``ScriptedChatModel`` + a real store on a temp DB); by default the
    model is built lazily (so building the agent needs no provider key) and the store from settings.
    ``is_high_risk`` overrides the gate policy (defaults to ``settings.operations_hitl``);
    ``layout_model`` AI-authors the approval card (None → the web client's literal fallback)."""
    settings = settings or get_settings()
    predicate = is_high_risk or _risk_predicate(settings.operations_hitl)
    _model = model
    _store = store

    def run(messages: list, *, config=None, memory_context: str = "") -> list[BaseMessage]:
        nonlocal _model, _store
        if _model is None:
            _model = init_chat_model(settings.model_for("operations"), temperature=0, streaming=True)
        if _store is None:
            _store = build_operations_store(settings)
        # CRUD tools (closing over the store) + present_ui (inline result cards) + memory tools. The
        # latter two are read-like and never gated (they don't mutate the business, so the risk
        # predicate returns False for them).
        tools = [*make_operations_tools(_store), present_ui, *MEMORY_TOOLS]
        # Recalled long-term memory + live runtime context (date/timezone) appended AFTER the static
        # base prompt so the cacheable prefix stays stable. Empty → prompt unchanged.
        runtime_context = runtime_context_block(config)
        system_prompt = (
            OPERATIONS_SYSTEM_PROMPT
            + (f"\n\n{memory_context}" if memory_context else "")
            + (f"\n\n{runtime_context}" if runtime_context else "")
        )
        # Recompiled per run; resume works because LangGraph keys subgraph checkpoints on the
        # node-name/structural path (not object identity) and we forward `config`.
        agent = _compile(_model, tools, predicate, layout_model, system_prompt)
        result = agent.invoke({"messages": messages}, config)
        return list(result["messages"][len(messages):])

    return run
