"""The operations services — the single source of truth for every business rule.

This is where "the limits of agentic development" are made *structural*. Nothing here trusts the
caller: ``create_order`` rejects an oversell, ``adjust_stock`` rejects a write-off that would
drive stock below zero, every mutation is transactional and leaves an audit-ledger entry. In
Phase 1 the caller is the REST API; in Phase 2 it will be an LLM agent tool — and because the
rules live *here*, not in the prompt, the agent simply cannot break them. It can ask; the service
decides.

Design contract (so Phase 2 is zero-rework):
- Every function takes an injected ``OperationsStore`` first, so it's testable against a
  disposable DB with no globals (mirrors how analytics functions take a ``SpiceDB``).
- Every mutation runs inside one ``store.tx()`` — the stock UPDATE and the ledger INSERT commit
  together or not at all.
- Every rejection raises ``OperationsError`` with a message written for a human to read (and, in
  Phase 2, for the model to read and self-correct from) — the deliberate analogue of ``SqlError``.
- Timestamps come from ``settings.data_as_of`` (never the wall clock), so runs are deterministic.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from nora.config import get_settings
from nora.observability import get_logger
from nora.operations import geo, routing
from nora.operations.errors import OperationsError
from nora.operations.interfaces import OperationsStore
from nora.operations.models import (
    LedgerEntry,
    Order,
    OrderItem,
    RoutePlan,
    RouteStop,
    StockRow,
)

log = get_logger(__name__)


# --- inputs ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class OrderLineInput:
    """One requested order line. Identify the product by id *or* sku."""

    quantity: int
    product_id: int | None = None
    sku: str | None = None


@dataclass(frozen=True)
class DeliveryInput:
    """An optional delivery attached to an order. Coords default to the city centroid."""

    address: str
    city: str
    lat: float | None = None
    lng: float | None = None
    window_start: str | None = None
    window_end: str | None = None


# --- helpers --------------------------------------------------------------------------------

_STOCK_SELECT = (
    "SELECT s.product_id, p.sku, p.name, s.on_hand, s.reserved, "
    "s.reorder_point, s.reorder_qty "
    "FROM stock_levels s JOIN ref_products p ON p.product_id = s.product_id"
)


def _timestamp() -> str:
    """Deterministic 'now' — the fixed `data_as_of` date, never the wall clock."""
    return get_settings().data_as_of.isoformat()


def _stock_row(row: dict) -> StockRow:
    """Build a StockRow from a `_STOCK_SELECT` row, filling the derived fields."""
    available = row["on_hand"] - row["reserved"]
    return StockRow(
        product_id=row["product_id"],
        sku=row["sku"],
        name=row["name"],
        on_hand=row["on_hand"],
        reserved=row["reserved"],
        available=available,
        reorder_point=row["reorder_point"],
        reorder_qty=row["reorder_qty"],
        low_stock=available <= row["reorder_point"],
    )


def _resolve_product(conn: sqlite3.Connection, *, product_id: int | None, sku: str | None) -> dict:
    """Resolve a product by id or sku within a transaction; raise if missing."""
    if product_id is not None:
        row = conn.execute(
            "SELECT product_id, sku, name, unit_price_lkr, active FROM ref_products "
            "WHERE product_id = ?",
            (product_id,),
        ).fetchone()
    elif sku is not None:
        row = conn.execute(
            "SELECT product_id, sku, name, unit_price_lkr, active FROM ref_products "
            "WHERE sku = ?",
            (sku,),
        ).fetchone()
    else:
        raise OperationsError("A product_id or sku is required.")
    if row is None:
        ident = f"id {product_id}" if product_id is not None else f"sku {sku!r}"
        raise OperationsError(f"Unknown product ({ident}).")
    return dict(row)


def _append_ledger(
    conn: sqlite3.Connection,
    *,
    product_id: int,
    kind: str,
    qty_delta: int,
    balance_after: int,
    reason: str | None,
    ref: str | None,
) -> None:
    conn.execute(
        "INSERT INTO stock_ledger "
        "(product_id, kind, qty_delta, balance_after, reason, ref, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (product_id, kind, qty_delta, balance_after, reason, ref, _timestamp()),
    )


# --- reads ----------------------------------------------------------------------------------

def list_stock(store: OperationsStore) -> list[StockRow]:
    """Every product's current stock position, by name."""
    return [_stock_row(r) for r in store.fetch_all(_STOCK_SELECT + " ORDER BY p.name")]


def list_low_stock(store: OperationsStore) -> list[StockRow]:
    """Products at or below their reorder point (available = on_hand - reserved)."""
    rows = store.fetch_all(
        _STOCK_SELECT + " WHERE (s.on_hand - s.reserved) <= s.reorder_point ORDER BY p.name"
    )
    return [_stock_row(r) for r in rows]


def get_stock(store: OperationsStore, product_id: int) -> StockRow:
    row = store.fetch_one(_STOCK_SELECT + " WHERE s.product_id = ?", (product_id,))
    if row is None:
        raise OperationsError(f"No stock record for product id {product_id}.")
    return _stock_row(row)


def get_ledger(store: OperationsStore, *, product_id: int | None = None) -> list[LedgerEntry]:
    sql = (
        "SELECT ledger_id, product_id, kind, qty_delta, balance_after, reason, ref, created_at "
        "FROM stock_ledger"
    )
    params: tuple = ()
    if product_id is not None:
        sql += " WHERE product_id = ?"
        params = (product_id,)
    sql += " ORDER BY ledger_id"
    return [LedgerEntry(**r) for r in store.fetch_all(sql, params)]


# --- stock mutations ------------------------------------------------------------------------

def receive_stock(
    store: OperationsStore,
    product_id: int,
    qty: int,
    *,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> StockRow:
    """Record inbound stock: on_hand += qty, with a ledger entry. Idempotent on
    ``idempotency_key`` — replaying the same key is a no-op that returns the current row."""
    if qty <= 0:
        raise OperationsError(f"Receive quantity must be positive (got {qty}).")

    with store.tx() as conn:
        if idempotency_key is not None:
            seen = conn.execute(
                "SELECT 1 FROM stock_ledger WHERE kind = 'receive' AND ref = ?",
                (idempotency_key,),
            ).fetchone()
            if seen is not None:
                return get_stock(store, product_id)  # already applied — no double count

        current = conn.execute(
            "SELECT on_hand FROM stock_levels WHERE product_id = ?", (product_id,)
        ).fetchone()
        if current is None:
            raise OperationsError(f"No stock record for product id {product_id}.")

        new_on_hand = current["on_hand"] + qty
        conn.execute(
            "UPDATE stock_levels SET on_hand = ? WHERE product_id = ?",
            (new_on_hand, product_id),
        )
        _append_ledger(
            conn,
            product_id=product_id,
            kind="receive",
            qty_delta=qty,
            balance_after=new_on_hand,
            reason=reason,
            ref=idempotency_key,
        )

    log.info("ops.receive", product_id=product_id, qty=qty, on_hand=new_on_hand)
    return get_stock(store, product_id)


def adjust_stock(
    store: OperationsStore,
    product_id: int,
    qty_delta: int,
    *,
    reason: str,
    kind: str = "adjust",
) -> StockRow:
    """Apply a manual stock correction or write-off (signed ``qty_delta``).

    Rejects (the "consequential state" limit): a delta of 0, a negative delta with no reason, and
    — the important one — any change that would drive on_hand below 0 or below what's already
    reserved for orders. You cannot write off stock you've promised to a customer.
    """
    if kind not in ("adjust", "write_off"):
        raise OperationsError(f"Invalid adjust kind {kind!r} (use 'adjust' or 'write_off').")
    if qty_delta == 0:
        raise OperationsError("Adjustment quantity must be non-zero.")
    if qty_delta < 0 and not (reason and reason.strip()):
        raise OperationsError("A reason is required for a negative adjustment / write-off.")

    with store.tx() as conn:
        current = conn.execute(
            "SELECT on_hand, reserved FROM stock_levels WHERE product_id = ?", (product_id,)
        ).fetchone()
        if current is None:
            raise OperationsError(f"No stock record for product id {product_id}.")

        new_on_hand = current["on_hand"] + qty_delta
        if new_on_hand < 0:
            log.info(
                "ops.write_off_rejected",
                product_id=product_id,
                qty_delta=qty_delta,
                on_hand=current["on_hand"],
                reserved=current["reserved"],
            )
            raise OperationsError(
                f"Adjustment of {qty_delta} would drive on_hand below zero "
                f"(currently {current['on_hand']})."
            )
        if new_on_hand < current["reserved"]:
            log.info(
                "ops.write_off_rejected",
                product_id=product_id,
                qty_delta=qty_delta,
                on_hand=current["on_hand"],
                reserved=current["reserved"],
            )
            raise OperationsError(
                f"Adjustment of {qty_delta} would leave on_hand ({new_on_hand}) below the "
                f"{current['reserved']} units already reserved for orders."
            )

        conn.execute(
            "UPDATE stock_levels SET on_hand = ? WHERE product_id = ?",
            (new_on_hand, product_id),
        )
        _append_ledger(
            conn,
            product_id=product_id,
            kind=kind,
            qty_delta=qty_delta,
            balance_after=new_on_hand,
            reason=reason,
            ref=None,
        )

    log.info("ops.adjust", product_id=product_id, qty_delta=qty_delta, on_hand=new_on_hand, reason=reason)
    return get_stock(store, product_id)


# --- orders ---------------------------------------------------------------------------------

def create_order(
    store: OperationsStore,
    customer_id: int,
    lines: list[OrderLineInput],
    *,
    delivery: DeliveryInput | None = None,
    idempotency_key: str | None = None,
) -> Order:
    """Create an order, reserving stock atomically. The heart of the "consequential state" limit.

    All in one transaction: validate the customer and every product (must exist + be active),
    **reject any oversell** (requested > on_hand − reserved), reserve the stock, compute **exact**
    integer totals, and optionally attach a delivery. Idempotent on ``idempotency_key`` (a replay
    returns the existing order without reserving twice).
    """
    if not lines:
        raise OperationsError("An order needs at least one line item.")

    with store.tx() as conn:
        if idempotency_key is not None:
            existing = conn.execute(
                "SELECT order_id FROM ops_orders WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if existing is not None:
                return get_order(store, existing["order_id"])  # replay — do not re-reserve

        customer = conn.execute(
            "SELECT customer_id, name FROM ref_customers WHERE customer_id = ?", (customer_id,)
        ).fetchone()
        if customer is None:
            raise OperationsError(f"Unknown customer (id {customer_id}).")

        # Resolve products and aggregate duplicate lines by product before the oversell check.
        wanted: dict[int, int] = {}
        meta: dict[int, dict] = {}
        for line in lines:
            if line.quantity <= 0:
                raise OperationsError(f"Line quantity must be positive (got {line.quantity}).")
            product = _resolve_product(conn, product_id=line.product_id, sku=line.sku)
            if not product["active"]:
                raise OperationsError(
                    f"Product {product['sku']} is inactive and cannot be ordered."
                )
            pid = product["product_id"]
            wanted[pid] = wanted.get(pid, 0) + line.quantity
            meta[pid] = product

        # Oversell check, per product, against currently-available stock.
        for pid, qty in wanted.items():
            stock = conn.execute(
                "SELECT on_hand, reserved FROM stock_levels WHERE product_id = ?", (pid,)
            ).fetchone()
            available = (stock["on_hand"] - stock["reserved"]) if stock else 0
            if qty > available:
                log.info("ops.oversell_rejected", product_id=pid, requested=qty, available=available)
                raise OperationsError(
                    f"Cannot reserve {qty} of {meta[pid]['sku']}: only {available} available."
                )

        # Passed every check — create the order, reserve stock, append the ledger.
        total = sum(qty * meta[pid]["unit_price_lkr"] for pid, qty in wanted.items())
        cur = conn.execute(
            "INSERT INTO ops_orders (customer_id, status, total_lkr, idempotency_key, created_at) "
            "VALUES (?, 'reserved', ?, ?, ?)",
            (customer_id, total, idempotency_key, _timestamp()),
        )
        order_id = cur.lastrowid

        for pid, qty in wanted.items():
            unit_price = meta[pid]["unit_price_lkr"]
            conn.execute(
                "INSERT INTO ops_order_items "
                "(order_id, product_id, quantity, unit_price_lkr, subtotal_lkr) "
                "VALUES (?, ?, ?, ?, ?)",
                (order_id, pid, qty, unit_price, qty * unit_price),
            )
            stock = conn.execute(
                "SELECT on_hand, reserved FROM stock_levels WHERE product_id = ?", (pid,)
            ).fetchone()
            conn.execute(
                "UPDATE stock_levels SET reserved = ? WHERE product_id = ?",
                (stock["reserved"] + qty, pid),
            )
            _append_ledger(
                conn,
                product_id=pid,
                kind="reserve",
                qty_delta=0,  # reservations move `reserved`, not `on_hand`
                balance_after=stock["on_hand"],
                reason=f"order #{order_id}",
                ref=f"order #{order_id}",
            )

        if delivery is not None:
            lat = delivery.lat if delivery.lat is not None else geo.coords_for_city(delivery.city)[0]
            lng = delivery.lng if delivery.lng is not None else geo.coords_for_city(delivery.city)[1]
            conn.execute(
                "INSERT INTO deliveries "
                "(order_id, address, city, lat, lng, status, route_id, window_start, window_end) "
                "VALUES (?, ?, ?, ?, ?, 'pending', NULL, ?, ?)",
                (order_id, delivery.address, delivery.city, lat, lng,
                 delivery.window_start, delivery.window_end),
            )

    log.info(
        "ops.order_created",
        order_id=order_id,
        customer_id=customer_id,
        total_lkr=total,
        lines=len(wanted),
    )
    return get_order(store, order_id)


def list_orders(store: OperationsStore, *, status: str | None = None) -> list[Order]:
    sql = "SELECT order_id FROM ops_orders"
    params: tuple = ()
    if status is not None:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY order_id"
    return [get_order(store, r["order_id"]) for r in store.fetch_all(sql, params)]


def get_order(store: OperationsStore, order_id: int) -> Order:
    head = store.fetch_one(
        "SELECT o.order_id, o.customer_id, c.name AS customer_name, o.status, o.total_lkr, "
        "o.created_at FROM ops_orders o JOIN ref_customers c ON c.customer_id = o.customer_id "
        "WHERE o.order_id = ?",
        (order_id,),
    )
    if head is None:
        raise OperationsError(f"Unknown order {order_id}.")
    item_rows = store.fetch_all(
        "SELECT i.product_id, p.sku, p.name, i.quantity, i.unit_price_lkr, i.subtotal_lkr "
        "FROM ops_order_items i JOIN ref_products p ON p.product_id = i.product_id "
        "WHERE i.order_id = ? ORDER BY i.order_item_id",
        (order_id,),
    )
    items = [OrderItem(**r) for r in item_rows]
    delivery = store.fetch_one(
        "SELECT delivery_id FROM deliveries WHERE order_id = ?", (order_id,)
    )
    return Order(
        order_id=head["order_id"],
        customer_id=head["customer_id"],
        customer_name=head["customer_name"],
        status=head["status"],
        total_lkr=head["total_lkr"],
        created_at=head["created_at"],
        items=items,
        delivery_id=delivery["delivery_id"] if delivery else None,
    )


# --- delivery routing -----------------------------------------------------------------------

def plan_route(
    store: OperationsStore,
    *,
    vehicle: str = "van-1",
    depot: tuple[float, float] | None = None,
) -> RoutePlan:
    """Plan a delivery route over all *pending* deliveries, using the deterministic optimizer.

    This is the handoff the whole project is about: the (future) agent gathers the stops and calls
    this; the *solver* — not the model — decides the order. We persist the route and report both
    the optimized length and the ``naive_km`` baseline so the win is auditable.
    """
    pending = store.fetch_all(
        "SELECT delivery_id, order_id, address, city, lat, lng "
        "FROM deliveries WHERE status = 'pending' ORDER BY delivery_id"
    )
    if not pending:
        raise OperationsError("No pending deliveries to plan a route for.")

    depot_pt = depot if depot is not None else geo.DEPOT
    points = [depot_pt] + [(d["lat"], d["lng"]) for d in pending]
    result = routing.plan(points)

    # result.order is node indices into `points` (0 = depot); map the stops back to deliveries.
    visit = [idx - 1 for idx in result.order if idx != 0]
    ordered_delivery_ids = [pending[i]["delivery_id"] for i in visit]

    with store.tx() as conn:
        cur = conn.execute(
            "INSERT INTO routes "
            "(vehicle, stop_sequence, total_km, naive_km, est_minutes, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'planned', ?)",
            (
                vehicle,
                json.dumps(ordered_delivery_ids),
                round(result.optimized_km, 3),
                round(result.naive_km, 3),
                round(result.est_minutes, 1),
                _timestamp(),
            ),
        )
        route_id = cur.lastrowid
        for did in ordered_delivery_ids:
            conn.execute(
                "UPDATE deliveries SET status = 'planned', route_id = ? WHERE delivery_id = ?",
                (route_id, did),
            )

    log.info(
        "ops.route_planned",
        route_id=route_id,
        stops=len(ordered_delivery_ids),
        total_km=round(result.optimized_km, 3),
        naive_km=round(result.naive_km, 3),
    )
    return get_route(store, route_id)


def get_route(store: OperationsStore, route_id: int) -> RoutePlan:
    r = store.fetch_one("SELECT * FROM routes WHERE route_id = ?", (route_id,))
    if r is None:
        raise OperationsError(f"Unknown route {route_id}.")
    sequence = json.loads(r["stop_sequence"])
    stops: list[RouteStop] = []
    for seq, did in enumerate(sequence, start=1):
        d = store.fetch_one(
            "SELECT delivery_id, order_id, address, city, lat, lng FROM deliveries "
            "WHERE delivery_id = ?",
            (did,),
        )
        if d is not None:
            stops.append(
                RouteStop(
                    seq=seq,
                    delivery_id=d["delivery_id"],
                    order_id=d["order_id"],
                    address=d["address"],
                    city=d["city"],
                    lat=d["lat"],
                    lng=d["lng"],
                )
            )
    improvement = (r["naive_km"] - r["total_km"]) / r["naive_km"] * 100.0 if r["naive_km"] else 0.0
    return RoutePlan(
        route_id=r["route_id"],
        vehicle=r["vehicle"],
        status=r["status"],
        total_km=r["total_km"],
        naive_km=r["naive_km"],
        est_minutes=r["est_minutes"],
        improvement_pct=round(improvement, 1),
        ordered_stops=stops,
    )


def dispatch_route(store: OperationsStore, route_id: int) -> RoutePlan:
    """Dispatch a planned route: ship its orders (reserved -> out the door) and mark everything
    dispatched. Rejects if the route is unknown or already dispatched. One transaction.

    In Phase 2 this is the irreversible step that sits behind a human-approval ``interrupt()`` —
    an agent can plan all day, but a person signs off before the van rolls.
    """
    with store.tx() as conn:
        route = conn.execute(
            "SELECT route_id, status FROM routes WHERE route_id = ?", (route_id,)
        ).fetchone()
        if route is None:
            raise OperationsError(f"Unknown route {route_id}.")
        if route["status"] != "planned":
            raise OperationsError(
                f"Route {route_id} is '{route['status']}', not 'planned' — nothing to dispatch."
            )

        deliveries = conn.execute(
            "SELECT delivery_id, order_id FROM deliveries WHERE route_id = ?", (route_id,)
        ).fetchall()
        dispatched_orders = 0
        for d in deliveries:
            order_id = d["order_id"]
            items = conn.execute(
                "SELECT product_id, quantity FROM ops_order_items WHERE order_id = ?",
                (order_id,),
            ).fetchall()
            for item in items:
                pid, qty = item["product_id"], item["quantity"]
                stock = conn.execute(
                    "SELECT on_hand, reserved FROM stock_levels WHERE product_id = ?", (pid,)
                ).fetchone()
                new_on_hand = stock["on_hand"] - qty
                conn.execute(
                    "UPDATE stock_levels SET on_hand = ?, reserved = ? WHERE product_id = ?",
                    (new_on_hand, stock["reserved"] - qty, pid),
                )
                _append_ledger(
                    conn,
                    product_id=pid,
                    kind="ship",
                    qty_delta=-qty,
                    balance_after=new_on_hand,
                    reason=f"dispatch route #{route_id}",
                    ref=f"order #{order_id}",
                )
            conn.execute(
                "UPDATE ops_orders SET status = 'dispatched' WHERE order_id = ?", (order_id,)
            )
            conn.execute(
                "UPDATE deliveries SET status = 'dispatched' WHERE delivery_id = ?",
                (d["delivery_id"],),
            )
            dispatched_orders += 1

        conn.execute(
            "UPDATE routes SET status = 'dispatched' WHERE route_id = ?", (route_id,)
        )

    log.info("ops.dispatched", route_id=route_id, deliveries=dispatched_orders)
    return get_route(store, route_id)
