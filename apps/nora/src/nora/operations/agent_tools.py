"""The operations agent's TOOLS — thin ``@tool`` wrappers over ``operations/services.py``.

Each tool closes over an injected ``OperationsStore`` (how the analytics tools reach their DB) and
CALLS a service function — it holds no business logic of its own. A rejected request raises
``OperationsError``, which the agent's gated tools node turns into a self-correction ToolMessage
(the twin of analytics' ``SqlError`` loop). Tools return JSON so the model reads a clean result.
"""

from __future__ import annotations

import json

from langchain_core.tools import BaseTool, tool

from nora.operations import services
from nora.operations.interfaces import OperationsStore
from nora.operations.models import as_dict
from nora.operations.services import DeliveryInput, OrderLineInput


def _dump(obj) -> str:
    """JSON-encode a service result (a frozen model or a list of them) for the model to read."""
    if isinstance(obj, list):
        return json.dumps([as_dict(o) for o in obj])
    return json.dumps(as_dict(obj))


def _lines(raw: list[dict]) -> list[OrderLineInput]:
    return [
        OrderLineInput(quantity=int(ln["quantity"]), product_id=ln.get("product_id"), sku=ln.get("sku"))
        for ln in raw
    ]


def make_operations_tools(store: OperationsStore) -> list[BaseTool]:
    """Build the operations CRUD tools bound to ``store``. Reads and writes both flow through the
    agent's gated tools node, which decides (from the tool name + args) which writes pause for the
    operator's approval before they run."""

    # -- reads ----------------------------------------------------------------------------
    @tool
    def list_stock() -> str:
        """List the current stock position (on_hand / reserved / available + low-stock flag) for
        every product."""
        return _dump(services.list_stock(store))

    @tool
    def list_low_stock() -> str:
        """List only the products at or below their reorder point (need restocking)."""
        return _dump(services.list_low_stock(store))

    @tool
    def get_stock(product_id: int) -> str:
        """Get one product's stock position by product_id."""
        return _dump(services.get_stock(store, product_id))

    @tool
    def get_ledger(product_id: int | None = None) -> str:
        """Read the stock movement ledger (audit trail), optionally filtered to one product_id."""
        return _dump(services.get_ledger(store, product_id=product_id))

    @tool
    def list_orders(status: str | None = None) -> str:
        """List orders, optionally filtered by status ('reserved' | 'dispatched' | 'cancelled')."""
        return _dump(services.list_orders(store, status=status))

    @tool
    def get_order(order_id: int) -> str:
        """Get one order (line items, total, status, delivery) by order_id."""
        return _dump(services.get_order(store, order_id))

    @tool
    def list_customers() -> str:
        """List every customer (id, name, city, and any contact fields)."""
        return _dump(services.list_customers(store))

    @tool
    def get_customer(customer_id: int) -> str:
        """Get one customer by customer_id."""
        return _dump(services.get_customer(store, customer_id))

    # -- order writes ---------------------------------------------------------------------
    @tool
    def create_order(customer_id: int, lines: list[dict], delivery: dict | None = None) -> str:
        """Create an order for a customer, reserving stock. `lines` is a list of
        {"sku" OR "product_id", "quantity"}. Optional `delivery` is {"address", "city"}. The service
        rejects an oversell, an unknown/inactive product, or an unknown customer."""
        d = DeliveryInput(address=delivery["address"], city=delivery["city"]) if delivery else None
        return _dump(services.create_order(store, customer_id, _lines(lines), delivery=d))

    @tool
    def edit_order(order_id: int, lines: list[dict]) -> str:
        """Replace a RESERVED order's line items with `lines` ({"sku" OR "product_id", "quantity"})
        and recompute the total. Releases the old reservations first, so the new set is checked
        against the freed stock. Only a reserved order can be edited."""
        return _dump(services.edit_order(store, order_id, _lines(lines)))

    @tool
    def cancel_order(order_id: int) -> str:
        """Cancel a RESERVED order, releasing its reserved stock. A dispatched order can't be
        cancelled."""
        return _dump(services.cancel_order(store, order_id))

    # -- stock writes ---------------------------------------------------------------------
    @tool
    def receive_stock(product_id: int, qty: int, reason: str | None = None) -> str:
        """Record inbound stock: add `qty` (a positive number) to a product's on_hand, with an
        optional reason."""
        return _dump(services.receive_stock(store, product_id, qty, reason=reason))

    @tool
    def adjust_stock(product_id: int, qty_delta: int, reason: str, kind: str = "adjust") -> str:
        """Apply a signed stock correction. `kind` is 'adjust' or 'write_off'. A negative delta needs
        a reason and cannot drive on_hand below zero or below what's already reserved for orders."""
        return _dump(services.adjust_stock(store, product_id, qty_delta, reason=reason, kind=kind))

    # -- customer writes ------------------------------------------------------------------
    @tool
    def create_customer(
        name: str,
        city: str,
        email: str | None = None,
        phone: str | None = None,
        address: str | None = None,
    ) -> str:
        """Add a new customer with a name + city (and optional email / phone / address)."""
        return _dump(
            services.create_customer(store, name, city, email=email, phone=phone, address=address)
        )

    @tool
    def update_customer(
        customer_id: int,
        name: str | None = None,
        city: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        address: str | None = None,
    ) -> str:
        """Update a customer's fields — only the ones you pass are changed."""
        return _dump(
            services.update_customer(
                store, customer_id, name=name, city=city, email=email, phone=phone, address=address
            )
        )

    @tool
    def delete_customer(customer_id: int) -> str:
        """Delete a customer. Rejected if the customer still has orders (cancel them first)."""
        services.delete_customer(store, customer_id)
        return json.dumps({"deleted_customer_id": customer_id})

    return [
        list_stock,
        list_low_stock,
        get_stock,
        get_ledger,
        list_orders,
        get_order,
        list_customers,
        get_customer,
        create_order,
        edit_order,
        cancel_order,
        receive_stock,
        adjust_stock,
        create_customer,
        update_customer,
        delete_customer,
    ]


# The write tools (used by the "all" HITL policy). Reads are everything else.
WRITE_TOOL_NAMES = frozenset(
    {
        "create_order",
        "edit_order",
        "cancel_order",
        "receive_stock",
        "adjust_stock",
        "create_customer",
        "update_customer",
        "delete_customer",
    }
)
