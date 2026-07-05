"""The operations DB schema — one place, as DDL constants.

A *writable* SQLite database, deliberately separate from the read-only bundled
`curry_nomad.db` so the committed demo dataset stays pristine. The shape is the substrate the
operations services mutate transactionally:

- ``ref_products`` / ``ref_customers`` — snapshots copied from the business DB at seed time, so
  this DB is self-contained (one read-write connection, FKs resolve locally, no cross-DB ATTACH).
- ``stock_levels`` — the current position per product (on_hand / reserved), with the core
  invariants (``reserved <= on_hand``, both ``>= 0``) enforced at the DB layer too.
- ``stock_ledger`` — an append-only audit trail: every movement, signed, with the balance after.
- ``ops_orders`` / ``ops_order_items`` — orders created here (distinct from the read-only
  business ``orders`` table); prices + subtotals stored as exact integer LKR.
- ``routes`` / ``deliveries`` — a planned vehicle run over an ordered set of delivery stops.

Tables are created in FK-dependency order; the store/seed turn ``PRAGMA foreign_keys=ON``.
"""

from __future__ import annotations

# Ledger movement kinds (documented here so the audit trail stays greppable).
LEDGER_KINDS = ("receive", "reserve", "release", "ship", "adjust", "write_off")

# The full schema, applied with `connection.executescript(DDL)` on a fresh file.
DDL = """
-- Reference snapshots (copied from the read-only business DB at seed time) -------------------
CREATE TABLE ref_products (
  product_id     INTEGER PRIMARY KEY,
  name           TEXT NOT NULL,
  sku            TEXT UNIQUE NOT NULL,
  category       TEXT NOT NULL,
  unit_price_lkr INTEGER NOT NULL,
  active         INTEGER NOT NULL
);

CREATE TABLE ref_customers (
  customer_id INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  city        TEXT NOT NULL,
  email       TEXT,                    -- nullable contact fields; the seed snapshot leaves them
  phone       TEXT,                    -- NULL (the business DB has none), the agent fills them in
  address     TEXT
);

-- Current stock position, one row per product ------------------------------------------------
CREATE TABLE stock_levels (
  product_id    INTEGER PRIMARY KEY REFERENCES ref_products(product_id),
  on_hand       INTEGER NOT NULL CHECK (on_hand >= 0),
  reserved      INTEGER NOT NULL CHECK (reserved >= 0),
  reorder_point INTEGER NOT NULL,
  reorder_qty   INTEGER NOT NULL,
  CHECK (reserved <= on_hand)            -- the core invariant, also guarded in services
);

-- Append-only audit trail of every stock movement --------------------------------------------
CREATE TABLE stock_ledger (
  ledger_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id    INTEGER NOT NULL REFERENCES ref_products(product_id),
  kind          TEXT NOT NULL,           -- one of LEDGER_KINDS
  qty_delta     INTEGER NOT NULL,        -- signed change to on_hand (0 for reserve/release)
  balance_after INTEGER NOT NULL,        -- on_hand AFTER this movement
  reason        TEXT,                    -- write-off reason, receipt note, ...
  ref           TEXT,                    -- correlating ref: 'order #N', idempotency key, ...
  created_at    TEXT NOT NULL            -- ISO; from settings.data_as_of (deterministic)
);
CREATE INDEX ix_ledger_product ON stock_ledger(product_id, ledger_id);

-- Routes: a planned vehicle run over an ordered set of delivery stops -------------------------
CREATE TABLE routes (
  route_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  vehicle       TEXT NOT NULL,
  stop_sequence TEXT NOT NULL,           -- JSON array of delivery_ids, in visit order
  total_km      REAL NOT NULL,           -- optimized tour length
  naive_km      REAL NOT NULL,           -- input-order baseline ("the agent's unplanned guess")
  est_minutes   REAL NOT NULL,
  status        TEXT NOT NULL,           -- 'planned' | 'dispatched'
  created_at    TEXT NOT NULL
);

-- Orders created here (DISTINCT from the read-only business `orders` table) -------------------
CREATE TABLE ops_orders (
  order_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id     INTEGER NOT NULL REFERENCES ref_customers(customer_id),
  status          TEXT NOT NULL,         -- 'reserved' | 'dispatched' | 'cancelled'
  total_lkr       INTEGER NOT NULL,      -- exact integer sum of line subtotals
  idempotency_key TEXT UNIQUE,           -- nullable; dedupes create_order retries
  created_at      TEXT NOT NULL
);

CREATE TABLE ops_order_items (
  order_item_id  INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id       INTEGER NOT NULL REFERENCES ops_orders(order_id),
  product_id     INTEGER NOT NULL REFERENCES ref_products(product_id),
  quantity       INTEGER NOT NULL CHECK (quantity > 0),
  unit_price_lkr INTEGER NOT NULL,       -- snapshotted from ref_products at order time
  subtotal_lkr   INTEGER NOT NULL        -- quantity * unit_price_lkr (stored exact)
);
CREATE INDEX ix_order_items_order ON ops_order_items(order_id);

-- Deliveries: one per order (Phase 1) --------------------------------------------------------
CREATE TABLE deliveries (
  delivery_id  INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id     INTEGER NOT NULL REFERENCES ops_orders(order_id),
  address      TEXT NOT NULL,
  city         TEXT NOT NULL,
  lat          REAL NOT NULL,
  lng          REAL NOT NULL,
  status       TEXT NOT NULL,            -- 'pending' | 'planned' | 'dispatched' | 'delivered'
  route_id     INTEGER REFERENCES routes(route_id),
  window_start TEXT,
  window_end   TEXT
);
CREATE INDEX ix_deliveries_status ON deliveries(status);
"""

# Tables, in FK-dependency order — handy for assertions and a fast "is this DB seeded?" check.
TABLES = (
    "ref_products",
    "ref_customers",
    "stock_levels",
    "stock_ledger",
    "routes",
    "ops_orders",
    "ops_order_items",
    "deliveries",
)
