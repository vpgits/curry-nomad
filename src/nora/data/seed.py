"""Deterministically build the bundled Curry Nomad SQLite database.

Determinism is the whole point: a fixed RNG seed (`random.Random(42)`), a fixed date window,
and zero wall-clock calls mean re-running this produces the same DB byte-for-byte — which is
what makes the analytics evals stable and ground-truth derivable from the data itself.

Run with:  `python -m nora.data.seed`  (writes to `settings.db_path`).

PLANTED TRUTHS (so demo questions land with clear signal):
  - Ceylon Cinnamon (Alba) and Roasted Curry Powder are deliberate top sellers (heaviest
    popularity weights), so "best/highest-revenue product" questions have an obvious answer.
  - Colombo is the heaviest city; export customers are rarer but place larger orders.
  - Blends and specialty items carry a higher refund rate (and skew the 'quality' reason),
    so "refund rate on blends" is meaningfully higher than the baseline.
  - All money is integer LKR. Orders span 2025-07-01 .. 2026-06-30 (= settings.data_as_of),
    so "last quarter" / "last month" / "this year" are deterministically answerable.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from nora.config import get_settings

# Fixed window: ends exactly on data_as_of so relative time queries are deterministic.
WINDOW_START = date(2025, 7, 1)
WINDOW_END = date(2026, 6, 30)
_CUSTOMER_SIGNUP_START = date(2024, 1, 1)

SEED = 42
N_CUSTOMERS = 120
N_ORDERS = 1500

# --- Product catalogue (18 SKUs). (name, category, origin, grams, unit_price_lkr, sku, popularity) ---
# popularity = relative weight for how often the product appears in an order item.
_PRODUCTS = [
    ("Ceylon Cinnamon (Alba)", "whole_spice", "Matale", 100, 1450, "CIN-ALBA-100", 10.0),
    ("Ceylon Cinnamon (C5)", "whole_spice", "Matale", 250, 2200, "CIN-C5-250", 4.0),
    ("Black Pepper", "whole_spice", "Kandy", 200, 1100, "PEP-BLK-200", 6.0),
    ("White Pepper", "whole_spice", "Kandy", 200, 1600, "PEP-WHT-200", 2.5),
    ("Green Cardamom", "whole_spice", "Kandy", 50, 1900, "CAR-GRN-050", 3.0),
    ("Cloves", "whole_spice", "Galle", 100, 1700, "CLV-WHL-100", 2.5),
    ("Nutmeg & Mace", "whole_spice", "Matale", 100, 1800, "NTM-MAC-100", 2.0),
    ("Turmeric Powder", "ground_spice", "Kurunegala", 200, 850, "TUR-PWD-200", 6.0),
    ("Chili Powder", "ground_spice", "Jaffna", 200, 950, "CHI-PWD-200", 5.5),
    ("Roasted Curry Powder", "blend", "Colombo", 200, 1250, "CUR-RST-200", 9.0),
    ("Unroasted Curry Powder", "blend", "Colombo", 200, 1200, "CUR-UNR-200", 4.0),
    ("Jaffna Curry Powder", "blend", "Jaffna", 200, 1350, "CUR-JAF-200", 3.5),
    ("Seafood Curry Mix", "blend", "Negombo", 150, 1400, "CUR-SEA-150", 2.5),
    ("Goraka (Garcinia)", "specialty", "Galle", 100, 700, "GOR-DRY-100", 2.0),
    ("Pandan & Rampe (dried)", "specialty", "Matara", 50, 600, "PAN-RAM-050", 1.5),
    ("Maldive Fish Flakes", "specialty", "Mirissa", 100, 2100, "MAL-FSH-100", 2.0),
    ("Cinnamon Sticks Gift Tin", "specialty", "Matale", 150, 3200, "CIN-TIN-150", 1.5),
    ("Curry Lover's Sampler Kit", "blend", "Colombo", 300, 2800, "KIT-SMP-300", 2.0),
]

_FIRST_NAMES = [
    "Nimal", "Kamal", "Sunil", "Saman", "Ruwan", "Chathura", "Dilshan", "Tharindu",
    "Ishara", "Nuwan", "Roshan", "Asanka", "Kasun", "Lahiru", "Sahan", "Pradeep",
    "Niluka", "Dilani", "Sanduni", "Hashini", "Iresha", "Tharushi", "Amaya", "Sewwandi",
    "Madhavi", "Nadeesha", "Kumari", "Shanika", "Piyumi", "Gayani", "Priya", "Lakshmi",
    "Vijay", "Suresh", "Mohan", "Rajiv", "Anush", "Menaka", "Subashini", "Kavya",
]
_LAST_NAMES = [
    "Perera", "Fernando", "Silva", "Jayawardena", "Bandara", "Wickramasinghe",
    "Gunawardena", "Rajapaksa", "Dissanayake", "Senanayake", "Wijesinghe", "Herath",
    "Ekanayake", "Rathnayake", "Karunaratne", "Mendis", "Peiris", "Samaraweera",
    "Sivakumar", "Raveendran", "Balasubramaniam", "Thevarajah", "Nadarajah",
]

# Cities: local (Colombo heaviest) and export (rarer, larger orders).
_LOCAL_CITIES = ["Colombo", "Colombo", "Colombo", "Kandy", "Kandy", "Galle", "Negombo", "Matara", "Jaffna"]
_EXPORT_CITIES = ["London", "Toronto", "Sydney", "Dubai", "Melbourne"]

_CHANNELS = ["web", "whatsapp", "market_stall", "wholesale"]
_CHANNEL_WEIGHTS = [0.5, 0.28, 0.15, 0.07]

_REFUND_REASONS = ["damaged", "late", "wrong_item", "quality"]

_SCHEMA = """
CREATE TABLE products (
  product_id     INTEGER PRIMARY KEY,
  name           TEXT NOT NULL,
  category       TEXT NOT NULL,
  origin         TEXT NOT NULL,
  grams          INTEGER NOT NULL,
  unit_price_lkr INTEGER NOT NULL,
  sku            TEXT UNIQUE NOT NULL,
  active         INTEGER NOT NULL
);
CREATE TABLE customers (
  customer_id INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  city        TEXT NOT NULL,
  segment     TEXT NOT NULL,
  created_at  TEXT NOT NULL
);
CREATE TABLE orders (
  order_id    INTEGER PRIMARY KEY,
  customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
  order_date  TEXT NOT NULL,
  status      TEXT NOT NULL,
  channel     TEXT NOT NULL
);
CREATE TABLE order_items (
  order_item_id  INTEGER PRIMARY KEY,
  order_id       INTEGER NOT NULL REFERENCES orders(order_id),
  product_id     INTEGER NOT NULL REFERENCES products(product_id),
  quantity       INTEGER NOT NULL,
  unit_price_lkr INTEGER NOT NULL
);
CREATE TABLE refunds (
  refund_id   INTEGER PRIMARY KEY,
  order_id    INTEGER NOT NULL REFERENCES orders(order_id),
  amount_lkr  INTEGER NOT NULL,
  reason      TEXT NOT NULL,
  refund_date TEXT NOT NULL
);
"""


def _iso(d: date) -> str:
    return d.isoformat()


def build(db_path: Path) -> Path:
    """Build the database at ``db_path`` (overwriting any existing file) and return the path."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()  # fresh build → deterministic, byte-for-byte reproducible

    rng = random.Random(SEED)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        _seed_products(conn)
        customers = _seed_customers(conn, rng)
        _seed_orders(conn, rng, customers)
        conn.commit()
    finally:
        conn.close()
    return db_path


def _seed_products(conn: sqlite3.Connection) -> None:
    rows = [
        (i, name, cat, origin, grams, price, sku, 1)
        for i, (name, cat, origin, grams, price, sku, _pop) in enumerate(_PRODUCTS, start=1)
    ]
    conn.executemany(
        "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
    )


def _seed_customers(conn: sqlite3.Connection, rng: random.Random) -> list[dict]:
    customers: list[dict] = []
    signup_span = (WINDOW_END - _CUSTOMER_SIGNUP_START).days
    for cid in range(1, N_CUSTOMERS + 1):
        name = f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)}"
        segment = "export" if rng.random() < 0.15 else "local"
        city = rng.choice(_EXPORT_CITIES if segment == "export" else _LOCAL_CITIES)
        created_at = _CUSTOMER_SIGNUP_START + timedelta(days=rng.randint(0, signup_span))
        customers.append({"id": cid, "segment": segment})
        conn.execute(
            "INSERT INTO customers VALUES (?, ?, ?, ?, ?)",
            (cid, name, city, segment, _iso(created_at)),
        )
    return customers


def _seed_orders(conn: sqlite3.Connection, rng: random.Random, customers: list[dict]) -> None:
    product_ids = list(range(1, len(_PRODUCTS) + 1))
    product_weights = [p[6] for p in _PRODUCTS]
    product_prices = [p[4] for p in _PRODUCTS]
    product_categories = [p[1] for p in _PRODUCTS]
    order_span = (WINDOW_END - WINDOW_START).days

    item_id = 0
    refund_id = 0
    for order_id in range(1, N_ORDERS + 1):
        cust = rng.choice(customers)
        is_export = cust["segment"] == "export"
        order_date = WINDOW_START + timedelta(days=rng.randint(0, order_span))
        channel = rng.choices(_CHANNELS, weights=_CHANNEL_WEIGHTS, k=1)[0]

        # Items: export orders are larger (more lines, higher quantities) but rarer.
        n_items = rng.randint(2, 5) if is_export else rng.randint(1, 3)
        chosen = rng.choices(product_ids, weights=product_weights, k=n_items)
        items: list[tuple[int, int, int]] = []  # (product_id, qty, price)
        order_total = 0
        has_blend = False
        for pid in chosen:
            qty = rng.randint(2, 8) if is_export else rng.randint(1, 4)
            price = product_prices[pid - 1]
            items.append((pid, qty, price))
            order_total += qty * price
            if product_categories[pid - 1] in ("blend", "specialty"):
                has_blend = True

        # Status: blends/specialty are more refund-prone (the planted truth the eval checks)
        # — roughly double the baseline refund rate.
        refund_prob = 0.035 + (0.035 if has_blend else 0.0)
        cancel_prob = 0.05
        roll = rng.random()
        if roll < cancel_prob:
            status = "cancelled"
        elif roll < cancel_prob + refund_prob:
            status = "refunded"
        else:
            status = "completed"

        conn.execute(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?)",
            (order_id, cust["id"], _iso(order_date), status, channel),
        )
        for pid, qty, price in items:
            item_id += 1
            conn.execute(
                "INSERT INTO order_items VALUES (?, ?, ?, ?, ?)",
                (item_id, order_id, pid, qty, price),
            )

        if status == "refunded":
            refund_id += 1
            frac = rng.uniform(0.3, 1.0)
            amount = max(1, int(order_total * frac))
            # Blends skew toward 'quality' complaints.
            reasons = ["quality", "quality", "damaged", "late", "wrong_item"] if has_blend else _REFUND_REASONS
            reason = rng.choice(reasons)
            refund_date = order_date + timedelta(days=rng.randint(1, 21))
            if refund_date > WINDOW_END:
                refund_date = WINDOW_END
            conn.execute(
                "INSERT INTO refunds VALUES (?, ?, ?, ?, ?)",
                (refund_id, order_id, amount, reason, _iso(refund_date)),
            )


def main() -> None:
    from nora.observability import get_logger

    log = get_logger(__name__)
    settings = get_settings()
    path = build(settings.db_path)
    # Quick row-count summary so the build is verifiable at a glance.
    conn = sqlite3.connect(path)
    try:
        counts = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("products", "customers", "orders", "order_items", "refunds")
        }
    finally:
        conn.close()
    log.info("seed.built", path=str(path), **counts)


if __name__ == "__main__":
    main()
