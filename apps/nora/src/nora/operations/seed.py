"""Deterministically build the writable operations DB from the read-only business DB.

Same discipline as `nora.data.seed`: deterministic by construction — zero wall-clock calls and no
RNG (delivery coordinates are hand-picked to match each address, not jittered) — so re-running
produces the same DB byte-for-byte. The read-only `curry_nomad.db` is the source of truth for the
*reference* data (products, customers) — we snapshot a subset into this DB so it's self-contained
— and the source of *initial stock*, derived from each product's real sales volume so the numbers
are plausible.

Run with:  `python -m nora.operations.seed`  (writes to `settings.ops_db_path`).

PLANTED TRUTHS (so the demo has signal):
  - Initial on_hand ≈ 1.5 months of historical demand; reorder points ≈ half a month.
  - A few SKUs (White Pepper, Green Cardamom, Cloves gift tin, Goraka) are deliberately seeded
    *below* their reorder point, so `/stock/low` is non-empty out of the box.
  - Eight pending deliveries — each a *complete* street address pinned to its real (lat, lng) — are
    seeded across local cities in a deliberately zig-zag order, so a naive "visit them as listed"
    route is clearly longer than the optimized one — the routing win is visible immediately.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from nora.config import get_settings
from nora.observability import get_logger
from nora.operations import geo, schema

# SKUs deliberately seeded below their reorder point (for the low-stock demo). Disjoint from the
# SKUs reserved by the seeded orders below, so reserved stays 0 and they read as cleanly "low".
_PLANTED_LOW = ("PEP-WHT-200", "CAR-GRN-050", "CIN-TIN-150", "GOR-DRY-100")

# SKUs the seeded orders reserve (top sellers with deep stock, so reservations are always safe).
_RESERVE_SKUS = ("CUR-RST-200", "CIN-ALBA-100")

# Eight pending deliveries, intentionally in a zig-zag order so the naive "as-listed" tour is long
# and the optimizer has real work to do. Each row is a *complete* street address (house number,
# street, suburb, city, postcode) pinned to its real (lat, lng) — coordinates are hand-picked to
# land on the actual neighbourhood (no jitter), so the map pins are honest and the route geometry
# is real. Fields: (city, address, lat, lng).
_SEED_DELIVERIES = [
    ("Colombo", "No. 215, Galle Road, Kollupitiya, Colombo 00300", 6.9085, 79.8525),
    ("Jaffna", "No. 40, Hospital Road, Chundikuli, Jaffna 40000", 9.6647, 80.0118),
    ("Galle", "No. 8, Lighthouse Street, Galle Fort, Galle 80000", 6.0263, 80.2172),
    ("Kandy", "No. 121, Peradeniya Road, Kandy 20000", 7.2889, 80.6285),
    ("Negombo", "No. 3, Lewis Place, Negombo 11500", 7.2112, 79.8372),
    ("Matara", "No. 14, Beach Road, Matara 81000", 5.9466, 80.5453),
    ("Colombo", "No. 90, Marine Drive, Bambalapitiya, Colombo 00400", 6.8798, 79.8543),
    ("Kandy", "No. 7, Temple Street, Kandy 20000", 7.2942, 80.6411),
]


def _read_source(source_db_path: Path) -> tuple[list[dict], list[dict], dict[int, int]]:
    """Read reference rows + per-product units sold from the read-only business DB."""
    conn = sqlite3.connect(f"file:{source_db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        products = [
            dict(r)
            for r in conn.execute(
                "SELECT product_id, name, sku, category, unit_price_lkr, active "
                "FROM products ORDER BY product_id"
            )
        ]
        customers = [
            dict(r)
            for r in conn.execute(
                "SELECT customer_id, name, city FROM customers ORDER BY customer_id"
            )
        ]
        sold = {
            r["product_id"]: r["sold"]
            for r in conn.execute(
                "SELECT product_id, COALESCE(SUM(quantity), 0) AS sold "
                "FROM order_items GROUP BY product_id"
            )
        }
    finally:
        conn.close()
    return products, customers, sold


def _seed_reference(conn: sqlite3.Connection, products: list[dict], customers: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO ref_products (product_id, name, sku, category, unit_price_lkr, active) "
        "VALUES (:product_id, :name, :sku, :category, :unit_price_lkr, :active)",
        products,
    )
    conn.executemany(
        "INSERT INTO ref_customers (customer_id, name, city) "
        "VALUES (:customer_id, :name, :city)",
        customers,
    )


def _seed_stock(
    conn: sqlite3.Connection, products: list[dict], sold: dict[int, int], now: str
) -> None:
    """Initial stock per product, derived from historical demand, plus an opening ledger entry."""
    for p in products:
        monthly = sold.get(p["product_id"], 0) / 12.0
        reorder_point = max(round(monthly * 0.5), 10)
        reorder_qty = max(round(monthly), 20)
        on_hand = max(round(monthly * 1.5), 20)
        if p["sku"] in _PLANTED_LOW:
            on_hand = max(1, round(reorder_point * 0.4))  # clearly below the reorder point
        conn.execute(
            "INSERT INTO stock_levels (product_id, on_hand, reserved, reorder_point, reorder_qty) "
            "VALUES (?, ?, 0, ?, ?)",
            (p["product_id"], on_hand, reorder_point, reorder_qty),
        )
        conn.execute(
            "INSERT INTO stock_ledger "
            "(product_id, kind, qty_delta, balance_after, reason, ref, created_at) "
            "VALUES (?, 'receive', ?, ?, 'opening balance', 'seed', ?)",
            (p["product_id"], on_hand, on_hand, now),
        )


def _seed_orders_and_deliveries(
    conn: sqlite3.Connection,
    products: list[dict],
    customers: list[dict],
    now: str,
) -> None:
    """Seed a handful of reserved orders, each with a pending delivery, so /orders and
    /routes/plan have real data on first run."""
    by_sku = {p["sku"]: p for p in products}
    local_customers = [c for c in customers if c["city"] in geo.LOCAL_CITIES]

    for i, (city, address, lat, lng) in enumerate(_SEED_DELIVERIES):
        customer = local_customers[i % len(local_customers)]
        product = by_sku[_RESERVE_SKUS[i % len(_RESERVE_SKUS)]]
        qty = 2
        total = qty * product["unit_price_lkr"]

        cur = conn.execute(
            "INSERT INTO ops_orders (customer_id, status, total_lkr, idempotency_key, created_at) "
            "VALUES (?, 'reserved', ?, NULL, ?)",
            (customer["customer_id"], total, now),
        )
        order_id = cur.lastrowid
        conn.execute(
            "INSERT INTO ops_order_items "
            "(order_id, product_id, quantity, unit_price_lkr, subtotal_lkr) "
            "VALUES (?, ?, ?, ?, ?)",
            (order_id, product["product_id"], qty, product["unit_price_lkr"], total),
        )
        stock = conn.execute(
            "SELECT on_hand, reserved FROM stock_levels WHERE product_id = ?",
            (product["product_id"],),
        ).fetchone()
        conn.execute(
            "UPDATE stock_levels SET reserved = ? WHERE product_id = ?",
            (stock["reserved"] + qty, product["product_id"]),
        )
        conn.execute(
            "INSERT INTO stock_ledger "
            "(product_id, kind, qty_delta, balance_after, reason, ref, created_at) "
            "VALUES (?, 'reserve', 0, ?, ?, ?, ?)",
            (product["product_id"], stock["on_hand"], f"order #{order_id}", f"order #{order_id}", now),
        )

        conn.execute(
            "INSERT INTO deliveries "
            "(order_id, address, city, lat, lng, status, route_id, window_start, window_end) "
            "VALUES (?, ?, ?, ?, ?, 'pending', NULL, NULL, NULL)",
            (order_id, address, city, lat, lng),
        )


def build(ops_db_path: Path, source_db_path: Path | None = None) -> Path:
    """Build the operations DB at ``ops_db_path`` (overwriting any existing file)."""
    settings = get_settings()
    ops_db_path = Path(ops_db_path)
    source_db_path = Path(source_db_path) if source_db_path is not None else settings.db_path
    now = settings.data_as_of.isoformat()

    ops_db_path.parent.mkdir(parents=True, exist_ok=True)
    if ops_db_path.exists():
        ops_db_path.unlink()  # fresh build → byte-for-byte reproducible

    products, customers, sold = _read_source(source_db_path)

    conn = sqlite3.connect(ops_db_path)
    conn.row_factory = sqlite3.Row  # name-indexable rows for the reserve/stock reads below
    try:
        conn.executescript(schema.DDL)
        conn.execute("PRAGMA foreign_keys = ON")
        _seed_reference(conn, products, customers)
        _seed_stock(conn, products, sold, now)
        _seed_orders_and_deliveries(conn, products, customers, now)
        conn.commit()
    finally:
        conn.close()
    return ops_db_path


def main() -> None:
    log = get_logger(__name__)
    settings = get_settings()
    path = build(settings.ops_db_path)
    conn = sqlite3.connect(path)
    try:
        counts = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("ref_products", "ops_orders", "deliveries")
        }
    finally:
        conn.close()
    log.info(
        "ops.seed.built",
        path=str(path),
        products=counts["ref_products"],
        orders=counts["ops_orders"],
        deliveries=counts["deliveries"],
    )


if __name__ == "__main__":
    main()
