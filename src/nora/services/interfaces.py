"""Ports: the interfaces external effects sit behind.

Keeping these as `Protocol`s means the graph code depends on a shape, not a concrete class,
so the bundled deterministic implementations can be swapped for real adapters without
touching any node. `SqlError` is the one typed exception the analytics tool surfaces so the
agent can read the DB error and self-correct.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from nora.schemas import VideoBrief


class SqlError(Exception):
    """Raised by the data layer for any rejected or failed SQL query.

    The message carries the DB/guard error text verbatim — `ToolNode(handle_tool_errors=...)`
    turns it into a ToolMessage so the model can repair the query and retry.
    """


@runtime_checkable
class SpiceDB(Protocol):
    """Read-only access to the Curry Nomad business database."""

    def list_tables(self) -> list[str]:
        ...

    def describe_table(self, table: str) -> dict:
        """Return ``{"columns": [{"name", "type"}], "sample_rows": [...]}``."""
        ...

    def run_sql(self, query: str) -> dict:
        """Return ``{"columns", "rows", "row_count"}``; raise ``SqlError`` on bad SQL."""
        ...


@runtime_checkable
class Renderer(Protocol):
    """Turns a finished VideoBrief into a rendered asset (or a placeholder stand-in)."""

    def render(self, brief: VideoBrief) -> dict:
        """Return ``{"status", "asset_ref" | None, "detail"}``."""
        ...
