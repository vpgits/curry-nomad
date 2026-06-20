"""Analytics tools — thin `@tool` wrappers over the bundled SpiceDB.

Read-only by design (gate by risk: there's no risk in a SELECT, so there's no gate). The
important detail is `run_sql`: it lets `SqlError` *propagate* so the graph's
`ToolNode(handle_tool_errors=...)` can turn the DB error into a ToolMessage the model reads
and repairs — the self-correction loop.

Tools return human-readable strings (what the model sees). The module-level SpiceDB is built
lazily from settings (no import-time side effects).
"""

from __future__ import annotations

from langchain.tools import tool

from nora.config import get_settings
from nora.observability import get_logger
from nora.services.spice_db import SqliteSpiceDB, build_spice_db

log = get_logger(__name__)

_db: SqliteSpiceDB | None = None


def _get_db() -> SqliteSpiceDB:
    """Lazily build (and cache) the module-level SpiceDB from settings."""
    global _db
    if _db is None:
        _db = build_spice_db(get_settings())
    return _db


def _format_rows(columns: list[str], rows: list[list], row_count: int) -> str:
    if not columns:
        return "(no columns returned)"
    header = " | ".join(columns)
    body = "\n".join(" | ".join(str(v) for v in r) for r in rows)
    return f"{header}\n{body}\n({row_count} row(s))" if body else f"{header}\n(0 rows)"


@tool
def list_tables() -> str:
    """List the tables available in the Curry Nomad database."""
    tables = _get_db().list_tables()
    return "Tables: " + ", ".join(tables)


@tool
def describe_table(table: str) -> str:
    """Show the columns (name + type) and a few sample rows for one table."""
    desc = _get_db().describe_table(table)
    cols = ", ".join(f"{c['name']} ({c['type']})" for c in desc["columns"])
    samples = "\n".join(str(r) for r in desc["sample_rows"])
    return f"Table {table}\nColumns: {cols}\nSample rows:\n{samples}"


@tool
def run_sql(query: str) -> str:
    """Run a read-only SQL query against the Curry Nomad database. SELECT only.

    On failure this raises, and the DB/guard error text is returned to you as a tool result
    so you can read it, fix the query, and try again.
    """
    import time

    start = time.monotonic()
    result = _get_db().run_sql(query)  # SqlError propagates → handled by ToolNode
    ms = round((time.monotonic() - start) * 1000, 1)
    log.info("sql.run", query=query, rows=result["row_count"], ms=ms)
    return _format_rows(result["columns"], result["rows"], result["row_count"])


ANALYTICS_TOOLS = [list_tables, describe_table, run_sql]
