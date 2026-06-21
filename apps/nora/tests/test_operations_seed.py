"""The operations seed must be deterministic (like the business seed) and must leave the planted
demo signal in place: low-stock items, snapshot counts that match the source, and pending stops.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from nora.operations import seed as ops_seed
from nora.operations import services
from nora.operations.store import SqliteOperationsStore


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_seed_is_byte_for_byte_reproducible(seeded_db: Path, tmp_path: Path):
    a = ops_seed.build(tmp_path / "a.db", source_db_path=seeded_db)
    b = ops_seed.build(tmp_path / "b.db", source_db_path=seeded_db)
    assert _sha256(a) == _sha256(b)


def test_reference_snapshot_matches_source(seeded_db: Path, seeded_ops_db: Path):
    src = sqlite3.connect(f"file:{seeded_db}?mode=ro", uri=True)
    ops = sqlite3.connect(seeded_ops_db)
    try:
        assert (
            ops.execute("SELECT COUNT(*) FROM ref_products").fetchone()[0]
            == src.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        )
        assert (
            ops.execute("SELECT COUNT(*) FROM ref_customers").fetchone()[0]
            == src.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        )
    finally:
        src.close()
        ops.close()


def test_planted_low_stock_is_present(seeded_ops_db: Path):
    store = SqliteOperationsStore(seeded_ops_db)
    low_skus = {row.sku for row in services.list_low_stock(store)}
    # the seed forces these below their reorder point
    assert {"PEP-WHT-200", "CAR-GRN-050"} <= low_skus


def test_pending_deliveries_seeded(seeded_ops_db: Path):
    conn = sqlite3.connect(seeded_ops_db)
    try:
        pending = conn.execute(
            "SELECT COUNT(*) FROM deliveries WHERE status = 'pending'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert pending == 8
