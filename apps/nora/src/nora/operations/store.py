"""SQLite-backed `OperationsStore` — the writable data layer.

The read-write counterpart to `SqliteSpiceDB`. Where that one opens `mode=ro` and guards SQL,
this one is opened read-write and exposes a `tx()` transaction so the services above can mutate
stock + append the ledger **atomically**. It is pure data access — zero business rules. A fresh
connection is opened per call (simplest correct choice across LangGraph's threads; the DB is
tiny), with `PRAGMA foreign_keys=ON` so the schema's referential + CHECK invariants are enforced.

Production swap: a `PostgresOperationsStore` implementing the same `OperationsStore` Protocol —
wiring only, no service change.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from nora.operations.errors import OperationsError


class SqliteOperationsStore:
    """Concrete `OperationsStore` over the writable operations SQLite file."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise OperationsError(
                f"Operations DB not found at {self.db_path}. "
                "Run `python -m nora.operations.seed` first."
            )

    # -- connection -------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open a fresh read-write connection. `isolation_level=None` puts us in autocommit
        mode so `tx()` can drive BEGIN/COMMIT/ROLLBACK explicitly."""
        conn = sqlite3.connect(self.db_path, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # -- transactions -----------------------------------------------------------------

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """One atomic transaction. `BEGIN IMMEDIATE` takes the write lock up front (so two
        concurrent writers serialize cleanly rather than racing to an upgrade), COMMIT on a
        clean exit, ROLLBACK on any exception — so a failed invariant check leaves no partial
        write behind."""
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    # -- reads ------------------------------------------------------------------------

    def fetch_one(self, sql: str, params: Sequence = ()) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row is not None else None
        finally:
            conn.close()

    def fetch_all(self, sql: str, params: Sequence = ()) -> list[dict]:
        conn = self._connect()
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()


def build_operations_store(settings) -> SqliteOperationsStore:
    """Factory from Settings (used by the REST API and, in Phase 2, the agent tools)."""
    return SqliteOperationsStore(db_path=settings.ops_db_path)
