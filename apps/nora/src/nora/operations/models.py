"""Return shapes for the operations services — frozen dataclasses, JSON-native.

Deliberately plain: every field is explicit (including computed ones like ``available`` and
``low_stock``) so ``dataclasses.asdict`` round-trips them straight to the REST layer, and so the
Phase-2 agent tools can hand them to the checkpointer's msgpack serializer without surprises. No
``@property`` (asdict would drop those) — the services fill the derived fields when they build
the row.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class StockRow:
    """A product's current stock position."""

    product_id: int
    sku: str
    name: str
    on_hand: int
    reserved: int
    available: int  # on_hand - reserved
    reorder_point: int
    reorder_qty: int
    low_stock: bool  # available <= reorder_point


@dataclass(frozen=True)
class LedgerEntry:
    """One row of the append-only stock ledger."""

    ledger_id: int
    product_id: int
    kind: str
    qty_delta: int
    balance_after: int
    reason: str | None
    ref: str | None
    created_at: str


@dataclass(frozen=True)
class OrderItem:
    product_id: int
    sku: str
    name: str
    quantity: int
    unit_price_lkr: int
    subtotal_lkr: int


@dataclass(frozen=True)
class Order:
    order_id: int
    customer_id: int
    customer_name: str
    status: str
    total_lkr: int
    created_at: str
    items: list[OrderItem] = field(default_factory=list)
    delivery_id: int | None = None


@dataclass(frozen=True)
class RouteStop:
    """One stop on a planned route, in visit order (seq 1..N)."""

    seq: int
    delivery_id: int
    order_id: int
    address: str
    city: str
    lat: float
    lng: float


@dataclass(frozen=True)
class RoutePlan:
    """The result of planning (and the persisted shape of) a delivery route.

    ``naive_km`` is the length of visiting the stops in their *input* order — the "no planning"
    baseline. ``improvement_pct`` is how much shorter the optimized tour is. Both exist from day
    one so Phase 2 can show "the agent's unordered guess vs the solver" with no schema change.
    """

    route_id: int
    vehicle: str
    status: str
    total_km: float
    naive_km: float
    est_minutes: float
    improvement_pct: float
    ordered_stops: list[RouteStop] = field(default_factory=list)


def as_dict(obj) -> dict:
    """Recursively convert a frozen operations model to a plain JSON-native dict."""
    return asdict(obj)
