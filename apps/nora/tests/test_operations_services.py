"""The services own every business invariant — so this is where the "limits" are pinned down:
no oversell, no writing off stock you've reserved, exact money, atomic reservations, idempotent
retries, and an audit ledger that always reconciles. Pure offline (no LLM, disposable DB).
"""

from __future__ import annotations

import pytest

from nora.operations import services
from nora.operations.errors import OperationsError
from nora.operations.services import DeliveryInput, OrderLineInput


def _pid(store, sku: str) -> int:
    row = store.fetch_one("SELECT product_id FROM ref_products WHERE sku = ?", (sku,))
    assert row is not None, f"seed missing {sku}"
    return row["product_id"]


def _unit_price(store, sku: str) -> int:
    return store.fetch_one("SELECT unit_price_lkr FROM ref_products WHERE sku = ?", (sku,))[
        "unit_price_lkr"
    ]


# --- receive --------------------------------------------------------------------------------

def test_receive_increments_on_hand_and_writes_ledger(ops_store):
    pid = _pid(ops_store, "CIN-ALBA-100")
    before = services.get_stock(ops_store, pid).on_hand

    row = services.receive_stock(ops_store, pid, 50, reason="restock")

    assert row.on_hand == before + 50
    ledger = services.get_ledger(ops_store, product_id=pid)
    last = ledger[-1]
    assert last.kind == "receive"
    assert last.qty_delta == 50
    assert last.balance_after == before + 50


def test_receive_rejects_non_positive(ops_store):
    pid = _pid(ops_store, "CIN-ALBA-100")
    with pytest.raises(OperationsError):
        services.receive_stock(ops_store, pid, 0)


def test_receive_is_idempotent_on_key(ops_store):
    pid = _pid(ops_store, "CIN-ALBA-100")
    before = services.get_stock(ops_store, pid).on_hand

    services.receive_stock(ops_store, pid, 30, idempotency_key="shipment-A")
    services.receive_stock(ops_store, pid, 30, idempotency_key="shipment-A")  # replay

    assert services.get_stock(ops_store, pid).on_hand == before + 30  # counted once


# --- adjust / write-off ---------------------------------------------------------------------

def test_write_off_below_zero_is_rejected(ops_store):
    pid = _pid(ops_store, "CIN-ALBA-100")
    on_hand = services.get_stock(ops_store, pid).on_hand
    with pytest.raises(OperationsError, match="below zero"):
        services.adjust_stock(ops_store, pid, -(on_hand + 1), reason="spill")
    assert services.get_stock(ops_store, pid).on_hand == on_hand  # unchanged (rolled back)


def test_write_off_below_reserved_is_rejected(ops_store):
    # Reserve some stock via an order, then try to write off more than what's left unreserved.
    pid = _pid(ops_store, "TUR-PWD-200")
    stock = services.get_stock(ops_store, pid)
    services.create_order(ops_store, 1, [OrderLineInput(quantity=stock.available, sku="TUR-PWD-200")])
    # Now available is 0 and everything on hand is reserved; any write-off breaches `reserved`.
    with pytest.raises(OperationsError, match="reserved"):
        services.adjust_stock(ops_store, pid, -1, reason="damage")


def test_negative_adjust_requires_reason(ops_store):
    pid = _pid(ops_store, "CIN-ALBA-100")
    with pytest.raises(OperationsError, match="reason"):
        services.adjust_stock(ops_store, pid, -5, reason="")


def test_valid_adjust_writes_ledger(ops_store):
    pid = _pid(ops_store, "CIN-ALBA-100")
    before = services.get_stock(ops_store, pid).on_hand
    row = services.adjust_stock(ops_store, pid, -3, reason="breakage", kind="write_off")
    assert row.on_hand == before - 3
    assert services.get_ledger(ops_store, product_id=pid)[-1].kind == "write_off"


# --- orders ---------------------------------------------------------------------------------

def test_create_order_reserves_and_computes_exact_total(ops_store):
    pid = _pid(ops_store, "CIN-ALBA-100")
    price = _unit_price(ops_store, "CIN-ALBA-100")
    before = services.get_stock(ops_store, pid)

    order = services.create_order(ops_store, 1, [OrderLineInput(quantity=3, sku="CIN-ALBA-100")])

    assert order.status == "reserved"
    assert order.total_lkr == 3 * price  # exact integer money
    assert order.items[0].subtotal_lkr == 3 * price
    after = services.get_stock(ops_store, pid)
    assert after.reserved == before.reserved + 3
    assert after.available == before.available - 3
    assert after.on_hand == before.on_hand  # reserving doesn't move on_hand


def test_oversell_is_rejected(ops_store):
    stock = services.get_stock(ops_store, _pid(ops_store, "CIN-ALBA-100"))
    with pytest.raises(OperationsError, match="available"):
        services.create_order(
            ops_store, 1, [OrderLineInput(quantity=stock.available + 1, sku="CIN-ALBA-100")]
        )


def test_unknown_sku_and_customer_rejected(ops_store):
    with pytest.raises(OperationsError, match="Unknown product"):
        services.create_order(ops_store, 1, [OrderLineInput(quantity=1, sku="NOPE-000")])
    with pytest.raises(OperationsError, match="Unknown customer"):
        services.create_order(ops_store, 999999, [OrderLineInput(quantity=1, sku="CIN-ALBA-100")])


def test_duplicate_lines_are_aggregated_for_oversell(ops_store):
    stock = services.get_stock(ops_store, _pid(ops_store, "CIN-ALBA-100"))
    half = stock.available // 2 + 1  # two of these exceed availability in aggregate
    with pytest.raises(OperationsError, match="available"):
        services.create_order(
            ops_store,
            1,
            [
                OrderLineInput(quantity=half, sku="CIN-ALBA-100"),
                OrderLineInput(quantity=half, sku="CIN-ALBA-100"),
            ],
        )


def test_create_order_is_idempotent_on_key(ops_store):
    pid = _pid(ops_store, "CIN-ALBA-100")
    before = services.get_stock(ops_store, pid).reserved

    o1 = services.create_order(
        ops_store, 1, [OrderLineInput(quantity=2, sku="CIN-ALBA-100")], idempotency_key="po-1"
    )
    o2 = services.create_order(
        ops_store, 1, [OrderLineInput(quantity=2, sku="CIN-ALBA-100")], idempotency_key="po-1"
    )

    assert o1.order_id == o2.order_id  # same order returned
    assert services.get_stock(ops_store, pid).reserved == before + 2  # reserved once, not twice


# --- ledger reconciliation ------------------------------------------------------------------

def test_ledger_reconciles_with_on_hand(ops_store):
    pid = _pid(ops_store, "CIN-ALBA-100")
    services.receive_stock(ops_store, pid, 40)
    services.create_order(ops_store, 1, [OrderLineInput(quantity=2, sku="CIN-ALBA-100")])
    services.adjust_stock(ops_store, pid, -5, reason="sampling")

    ledger = services.get_ledger(ops_store, product_id=pid)
    assert sum(e.qty_delta for e in ledger) == services.get_stock(ops_store, pid).on_hand


# --- routing + dispatch ---------------------------------------------------------------------

def test_plan_route_persists_and_optimizes(ops_store):
    plan = services.plan_route(ops_store)
    assert plan.status == "planned"
    assert len(plan.ordered_stops) == 8  # the seeded pending deliveries
    assert plan.naive_km > 0
    assert plan.total_km <= plan.naive_km
    # planning consumes the pending deliveries — a second plan has nothing to do
    with pytest.raises(OperationsError, match="No pending deliveries"):
        services.plan_route(ops_store)


def test_dispatch_ships_reserved_stock_and_is_not_repeatable(ops_store):
    pid = _pid(ops_store, "CIN-ALBA-100")
    on_hand_before = services.get_stock(ops_store, pid).on_hand
    reserved_before = services.get_stock(ops_store, pid).reserved

    plan = services.plan_route(ops_store)
    dispatched = services.dispatch_route(ops_store, plan.route_id)
    assert dispatched.status == "dispatched"

    after = services.get_stock(ops_store, pid)
    # the seeded orders reserved CIN-ALBA-100; dispatch turns reservations into shipments
    assert after.on_hand == on_hand_before - reserved_before
    assert after.reserved == 0
    assert any(e.kind == "ship" for e in services.get_ledger(ops_store, product_id=pid))

    with pytest.raises(OperationsError, match="not 'planned'"):
        services.dispatch_route(ops_store, plan.route_id)


def test_order_with_delivery_creates_a_pending_stop(ops_store):
    order = services.create_order(
        ops_store,
        1,
        [OrderLineInput(quantity=1, sku="CIN-ALBA-100")],
        delivery=DeliveryInput(address="1 Test Rd", city="Galle"),
    )
    assert order.delivery_id is not None
    row = ops_store.fetch_one(
        "SELECT city, status FROM deliveries WHERE delivery_id = ?", (order.delivery_id,)
    )
    assert row["city"] == "Galle"
    assert row["status"] == "pending"
