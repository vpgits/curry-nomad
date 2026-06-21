"""The operations port: data access the services sit behind.

Mirrors `services/interfaces.py:SpiceDB` — the services depend on this *shape*, not on SQLite,
so a Postgres adapter (or any other) drops in with no service or graph change. The store is pure
data access: it knows how to read rows and how to run a transaction; it holds **no** business
rules (those live in `services.py`). ``tx()`` is the seam that makes a mutation atomic — the
service does its reads, its UPDATEs, and its ledger INSERT inside one ``with store.tx() as conn``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable


@runtime_checkable
class OperationsStore(Protocol):
    """Read-write access to the operations database."""

    def tx(self) -> AbstractContextManager[sqlite3.Connection]:
        """A single transaction: ``BEGIN IMMEDIATE`` on enter, ``COMMIT`` on clean exit,
        ``ROLLBACK`` on any exception. Yields the connection to run statements on."""
        ...

    def fetch_one(self, sql: str, params: Sequence = ()) -> dict | None:
        """Run a read query, return the first row as a dict (or ``None``)."""
        ...

    def fetch_all(self, sql: str, params: Sequence = ()) -> list[dict]:
        """Run a read query, return all rows as dicts."""
        ...
