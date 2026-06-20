"""Tests for the SQLite SpiceDB data layer + the deterministic seed (M0).

Covers the acceptance checks: a known query returns expected rows; `run_sql` rejects
non-SELECT / chained statements; enforces LIMIT; raises SqlError on bad SQL; and the seed is
byte-for-byte reproducible.
"""

from __future__ import annotations

import hashlib
import sqlite3

import pytest

from nora.data import seed
from nora.services.interfaces import SqlError
from nora.services.spice_db import SqliteSpiceDB


def test_lists_all_tables(spice_db: SqliteSpiceDB):
    assert set(spice_db.list_tables()) == {
        "products",
        "customers",
        "orders",
        "order_items",
        "refunds",
    }


def test_describe_table_shape(spice_db: SqliteSpiceDB):
    desc = spice_db.describe_table("products")
    col_names = {c["name"] for c in desc["columns"]}
    assert {"product_id", "name", "category", "origin", "unit_price_lkr"} <= col_names
    assert len(desc["sample_rows"]) == 3


def test_describe_unknown_table_raises(spice_db: SqliteSpiceDB):
    with pytest.raises(SqlError):
        spice_db.describe_table("not_a_table")


def test_known_query_returns_expected_rows(spice_db: SqliteSpiceDB):
    result = spice_db.run_sql("SELECT COUNT(*) AS n FROM products")
    assert result["columns"] == ["n"]
    assert result["rows"][0][0] == len(seed._PRODUCTS) == 18


def test_top_seller_has_signal(spice_db: SqliteSpiceDB):
    """The planted top sellers should actually dominate revenue (signal for the demo)."""
    result = spice_db.run_sql(
        "SELECT p.name, SUM(oi.quantity * oi.unit_price_lkr) AS rev "
        "FROM order_items oi "
        "JOIN orders o ON o.order_id = oi.order_id "
        "JOIN products p ON p.product_id = oi.product_id "
        "WHERE o.status != 'cancelled' "
        "GROUP BY p.product_id ORDER BY rev DESC LIMIT 1"
    )
    top_product = result["rows"][0][0]
    assert top_product in {"Ceylon Cinnamon (Alba)", "Roasted Curry Powder"}


def test_rejects_non_select(spice_db: SqliteSpiceDB):
    for bad in ["DELETE FROM products", "UPDATE products SET active=0", "DROP TABLE orders", "PRAGMA table_info(products)"]:
        with pytest.raises(SqlError):
            spice_db.run_sql(bad)


def test_rejects_chained_statements(spice_db: SqliteSpiceDB):
    with pytest.raises(SqlError):
        spice_db.run_sql("SELECT 1; DROP TABLE products")


def test_read_only_connection_blocks_writes(seeded_db):
    """Even if a guard were bypassed, the read-only connection refuses writes."""
    db = SqliteSpiceDB(seeded_db)
    # Bypass the keyword guard by calling _connect directly; mode=ro must still reject.
    conn = db._connect()
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM products")
    finally:
        conn.close()


def test_enforces_limit(seeded_db):
    db = SqliteSpiceDB(seeded_db, max_sql_rows=5)
    result = db.run_sql("SELECT * FROM order_items")  # thousands of rows, no LIMIT
    assert result["row_count"] == 5


def test_explicit_limit_preserved(seeded_db):
    db = SqliteSpiceDB(seeded_db, max_sql_rows=5)
    result = db.run_sql("SELECT * FROM order_items LIMIT 10")
    assert result["row_count"] == 10


def test_bad_sql_raises_sqlerror(spice_db: SqliteSpiceDB):
    with pytest.raises(SqlError):
        spice_db.run_sql("SELECT * FROM nonexistent_table")
    with pytest.raises(SqlError):
        spice_db.run_sql("SELECT bogus_column FROM products")


def test_seed_is_byte_for_byte_reproducible(tmp_path):
    a = tmp_path / "a.db"
    b = tmp_path / "b.db"
    seed.build(a)
    seed.build(b)
    assert hashlib.sha256(a.read_bytes()).hexdigest() == hashlib.sha256(b.read_bytes()).hexdigest()
