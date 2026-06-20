"""SQLite-backed SpiceDB — the bundled, deterministic data layer.

This is where the "safe tool" lesson lives. `run_sql` is the only place SQL from the model
touches the database, and it is guarded three ways (defense in depth):

  1. **SELECT-only.** The first keyword must be SELECT or WITH; chained statements
     (`;`-separated), PRAGMA, and any DDL/DML are rejected before execution. The connection
     is *also* opened read-only (`mode=ro`), so even a guard miss cannot mutate data.
  2. **Bounded.** A `LIMIT <max_sql_rows>` is injected if the query has none.
  3. **Time-boxed.** A progress handler aborts queries that run past `sql_timeout_s`.

Any rejection or DB error is raised as `SqlError(<message>)` so the agent can read it and
repair the query. A fresh read-only connection is opened per call — simplest correct choice
for use across LangGraph's threads, and the bundled DB is tiny.
"""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

from nora.services.interfaces import SqlError

# Queries must start with one of these. Everything else (INSERT/UPDATE/DELETE/DROP/PRAGMA/
# ATTACH/...) is rejected up front.
_ALLOWED_PREFIXES = ("select", "with")
# Rough VM-instruction granularity for the timeout progress handler.
_PROGRESS_OP_COUNT = 1000


class SqliteSpiceDB:
    """Concrete `SpiceDB` over the bundled SQLite file."""

    def __init__(self, db_path: Path, max_sql_rows: int = 200, sql_timeout_s: float = 5.0):
        self.db_path = Path(db_path)
        self.max_sql_rows = max_sql_rows
        self.sql_timeout_s = sql_timeout_s
        if not self.db_path.exists():
            raise SqlError(
                f"Database not found at {self.db_path}. Run `python -m nora.data.seed` first."
            )

    # -- connection -------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open a fresh read-only connection with a wall-clock statement timeout."""
        conn = sqlite3.connect(
            f"file:{self.db_path}?mode=ro", uri=True, check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        deadline = time.monotonic() + self.sql_timeout_s
        conn.set_progress_handler(
            lambda: 1 if time.monotonic() > deadline else 0, _PROGRESS_OP_COUNT
        )
        return conn

    # -- schema introspection ---------------------------------------------------------

    def list_tables(self) -> list[str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            return [r["name"] for r in rows]
        finally:
            conn.close()

    def describe_table(self, table: str) -> dict:
        if table not in self.list_tables():
            raise SqlError(f"Unknown table: {table!r}. Use list_tables to see what exists.")
        conn = self._connect()
        try:
            cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            columns = [{"name": c["name"], "type": c["type"]} for c in cols]
            sample = conn.execute(f'SELECT * FROM "{table}" LIMIT 3').fetchall()
            sample_rows = [dict(r) for r in sample]
            return {"columns": columns, "sample_rows": sample_rows}
        except sqlite3.Error as e:
            raise SqlError(str(e)) from e
        finally:
            conn.close()

    # -- the guarded query path -------------------------------------------------------

    def run_sql(self, query: str) -> dict:
        safe_query = self._guard(query)
        conn = self._connect()
        try:
            cur = conn.execute(safe_query)
            rows = cur.fetchall()
            columns = [d[0] for d in cur.description] if cur.description else []
            return {
                "columns": columns,
                "rows": [list(r) for r in rows],
                "row_count": len(rows),
            }
        except sqlite3.Error as e:
            # Surface the DB error verbatim so the agent can repair and retry.
            raise SqlError(str(e)) from e
        finally:
            conn.close()

    # -- guards -----------------------------------------------------------------------

    def _guard(self, query: str) -> str:
        """Reject non-SELECT / chained statements and enforce a LIMIT."""
        stripped = query.strip().rstrip(";").strip()
        if not stripped:
            raise SqlError("Empty query.")

        # Block chained statements (a `;` followed by more SQL).
        if ";" in stripped:
            raise SqlError("Only a single statement is allowed (no ';'-chained statements).")

        first_word = stripped.split(None, 1)[0].lower()
        if first_word not in _ALLOWED_PREFIXES:
            raise SqlError(
                f"Only read-only SELECT/WITH queries are allowed (got {first_word!r})."
            )

        # Inject a LIMIT if the query lacks one (word-boundary match, case-insensitive).
        if not re.search(r"\blimit\b", stripped, flags=re.IGNORECASE):
            stripped = f"{stripped}\nLIMIT {self.max_sql_rows}"
        return stripped


def build_spice_db(settings) -> SqliteSpiceDB:
    """Factory from Settings (used by the analytics tools)."""
    return SqliteSpiceDB(
        db_path=settings.db_path,
        max_sql_rows=settings.max_sql_rows,
        sql_timeout_s=settings.sql_timeout_s,
    )
