"""Offline tests for the `operations` capability (the orders/stock/customers CRUD agent).

Same scripted-fake approach as the workspace suite, driven through the orchestrator so the HITL
interrupt/resume exercises the real checkpointer path:
- a `ScriptedChatModel` drives the operations loop (tool call → final answer), and
- the tools call the REAL services against a disposable seeded ops DB (the `ops_store` fixture), so a
  rejected request (oversell, etc.) raises a real `OperationsError` the loop self-corrects from.

The capability is pinned OFF for the suite (conftest), so these set `operations_enabled=True` and
inject a store on a temp DB — no provider key, no network, no touching the on-disk ops DB.
"""

from __future__ import annotations

import asyncio

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from nora.config import Settings
from nora.operations import services
from nora.operations.agent import OPERATIONS_APPROVAL_KIND, build_operations_agent
from nora.orchestrator import build_orchestrator
from tests.fakes import ScriptedChatModel, ai_final, ai_tool_call


def _run(graph, *args, **kwargs):
    """The orchestrator is async (the workspace node is async); drive it via ainvoke from a sync test."""
    return asyncio.run(graph.ainvoke(*args, **kwargs))


def _stub_node(*args, **kwargs):  # noqa: ARG001 — never reached on an operations-routed turn
    raise AssertionError("only the operations capability should run on an operations request")


def _interrupt_payload(state) -> dict | None:
    pending = state.get("__interrupt__")
    if not pending:
        return None
    first = pending[0]
    return getattr(first, "value", first)


def _ops_orch(ops_model, ops_store):
    """Orchestrator wired to delegate to `operations` (with stubbed analytics/marketing), the ops agent
    running the scripted model against the disposable store, and a checkpointer so HITL resumes."""
    agent = build_operations_agent(
        settings=Settings(operations_enabled=True),
        model=ops_model,
        store=ops_store,
        layout_model=None,  # no key offline → the web client renders its own literal card
    )
    return build_orchestrator(
        settings=Settings(workspace_enabled=False, operations_enabled=True),
        supervisor_model=ScriptedChatModel(
            [ai_tool_call("to_operations", {"task": "manage operations"}, "h1"), ai_final("")]
        ),
        analytics_graph=_stub_node,
        marketing_graph=_stub_node,
        operations_agent=agent,
        checkpointer=InMemorySaver(),
    )


# --- reads + self-correction (ungated) ------------------------------------------------------

def test_operations_read_runs_the_tool_loop(ops_store):
    """A read tool (never gated) runs against the real services and the model answers from the result."""
    model = ScriptedChatModel(
        [
            ai_tool_call("list_low_stock", {}, "c1"),
            ai_final("Four SKUs are below their reorder point."),
        ]
    )
    orch = _ops_orch(model, ops_store)
    result = _run(
        orch,
        {"messages": [HumanMessage("what's low on stock?")]},
        {"configurable": {"thread_id": "o-read"}},
    )
    assert "below their reorder point" in result["messages"][-1].content


def test_operations_oversell_self_corrects(ops_store):
    """A create_order that oversells raises OperationsError; the gated node turns it into a
    self-correction ToolMessage the model reads and answers from — the analytics-contrast teaching
    point. create_order is LOW-risk under the default policy, so it runs with no approval pause."""
    stock = services.get_stock(ops_store, services.list_low_stock(ops_store)[0].product_id)
    model = ScriptedChatModel(
        [
            ai_tool_call(
                "create_order",
                {"customer_id": 1, "lines": [{"product_id": stock.product_id, "quantity": stock.available + 100}]},
                "c1",
            ),
            ai_final("I couldn't create that order — there isn't enough stock available."),
        ]
    )
    orch = _ops_orch(model, ops_store)
    result = _run(
        orch,
        {"messages": [HumanMessage("order a truckload")]},
        {"configurable": {"thread_id": "o-oversell"}},
    )
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert any("was rejected" in (m.content or "") for m in tool_msgs)
    assert "couldn't create that order" in result["messages"][-1].content


def test_operations_low_risk_write_runs_without_a_pause(ops_store):
    """receive_stock is low-risk → it runs straight through (no interrupt), and the stock actually
    moves against the real store."""
    pid = services.list_low_stock(ops_store)[0].product_id
    before = services.get_stock(ops_store, pid).on_hand
    model = ScriptedChatModel(
        [
            ai_tool_call("receive_stock", {"product_id": pid, "qty": 40, "reason": "restock"}, "c1"),
            ai_final("Received 40 units."),
        ]
    )
    orch = _ops_orch(model, ops_store)
    result = _run(
        orch,
        {"messages": [HumanMessage("receive 40 units")]},
        {"configurable": {"thread_id": "o-receive"}},
    )
    assert _interrupt_payload(result) is None  # low-risk → never paused
    assert services.get_stock(ops_store, pid).on_hand == before + 40


# --- HITL on high-risk writes ---------------------------------------------------------------

def test_operations_high_risk_cancel_pauses_then_runs_on_approve(ops_store):
    """The load-bearing test: cancel_order (high-risk) must pause at the approval gate; the interrupt
    RAISED in the per-run-recompiled subgraph must bubble up to pause the orchestrator, and a
    Command(resume=…) on the same thread must RESUME (not restart) so the approved cancel finally runs
    and releases the reservation."""
    order = services.list_orders(ops_store, status="reserved")[0]
    pid = order.items[0].product_id
    reserved_before = services.get_stock(ops_store, pid).reserved

    model = ScriptedChatModel(
        [
            ai_tool_call("cancel_order", {"order_id": order.order_id}, "c1"),
            ai_final(f"Cancelled order {order.order_id} and released the stock."),
        ]
    )
    orch = _ops_orch(model, ops_store)
    config = {"configurable": {"thread_id": "o-cancel"}}

    # Phase 1 — runs to the gate. The order must still be reserved (nothing ran yet).
    paused = _run(orch, {"messages": [HumanMessage(f"cancel order {order.order_id}")]}, config)
    payload = _interrupt_payload(paused)
    assert payload is not None, "the high-risk cancel should have paused the run"
    assert payload["kind"] == OPERATIONS_APPROVAL_KIND
    assert [a["name"] for a in payload["action_requests"]] == ["cancel_order"]
    assert services.get_order(ops_store, order.order_id).status == "reserved"  # not cancelled yet

    # Phase 2 — approve on the SAME thread. The subgraph resumes at the gate and runs the cancel.
    resumed = _run(orch, Command(resume={"decisions": [{"type": "approve"}]}), config)
    assert services.get_order(ops_store, order.order_id).status == "cancelled"
    assert services.get_stock(ops_store, pid).reserved == reserved_before - order.items[0].quantity
    assert f"Cancelled order {order.order_id}" in resumed["messages"][-1].content


def test_operations_high_risk_reject_skips_the_write(ops_store):
    """Rejecting a high-risk write must NOT run it; a synthetic ToolMessage tells the model the operator
    declined, and the model self-corrects into a graceful reply."""
    order = services.list_orders(ops_store, status="reserved")[0]
    model = ScriptedChatModel(
        [
            ai_tool_call("cancel_order", {"order_id": order.order_id}, "c1"),
            ai_final("Okay, I'll leave that order as it is."),
        ]
    )
    orch = _ops_orch(model, ops_store)
    config = {"configurable": {"thread_id": "o-reject"}}

    paused = _run(orch, {"messages": [HumanMessage("cancel it")]}, config)
    assert _interrupt_payload(paused)["kind"] == OPERATIONS_APPROVAL_KIND

    resumed = _run(orch, Command(resume={"decisions": [{"type": "reject", "message": "Keep it."}]}), config)
    assert services.get_order(ops_store, order.order_id).status == "reserved"  # never cancelled
    tool_msgs = [m for m in resumed["messages"] if isinstance(m, ToolMessage)]
    assert any("Keep it." in (m.content or "") for m in tool_msgs)
    assert "leave that order" in resumed["messages"][-1].content


def test_operations_add_customer_low_risk_and_persists(ops_store):
    """create_customer is low-risk → runs without a pause and persists the contact fields."""
    model = ScriptedChatModel(
        [
            ai_tool_call(
                "create_customer",
                {"name": "Priya Fernando", "city": "Dehiwala", "email": "priya@example.com"},
                "c1",
            ),
            ai_final("Added Priya Fernando (Dehiwala)."),
        ]
    )
    orch = _ops_orch(model, ops_store)
    result = _run(
        orch,
        {"messages": [HumanMessage("add a customer Priya in Dehiwala")]},
        {"configurable": {"thread_id": "o-cust"}},
    )
    assert _interrupt_payload(result) is None
    names = {c.name for c in services.list_customers(ops_store)}
    assert "Priya Fernando" in names


def test_operations_first_party_default_wires_the_node():
    """The shipped default (operations_enabled=True) AUTO-builds the operations agent + node with no
    provider key (model + store are lazy) — proving the capability is wired without injection. A
    non-operations turn (the supervisor answers directly) runs fine; the operations node is compiled
    in but never invoked, so no key or DB is touched."""
    orch = build_orchestrator(
        settings=Settings(operations_enabled=True, workspace_enabled=False),
        supervisor_model=ScriptedChatModel([ai_final("hi")]),
        analytics_graph=_stub_node,
        marketing_graph=_stub_node,
        checkpointer=InMemorySaver(),
    )
    result = _run(orch, {"messages": [HumanMessage("hello")]}, {"configurable": {"thread_id": "o-default"}})
    assert result["messages"][-1].content == "hi"
