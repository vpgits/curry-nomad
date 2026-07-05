"""Ports: the interfaces external effects sit behind.

Keeping these as `Protocol`s means the graph code depends on a shape, not a concrete class,
so the bundled deterministic implementations can be swapped for real adapters without
touching any node. `SqlError` is the one typed exception the analytics tool surfaces so the
agent can read the DB error and self-correct.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from nora.schemas import PostBrief


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
    """Turns a finished PostBrief into rendered images (or a placeholder stand-in).

    Rendering is staged so a human-review gate can sit between generating the images and finalizing
    the Instagram post: ``render_stills`` generates the hero + per-shot stills; the operator approves
    (or asks to ``regenerate_stills`` specific shots) before the post is finalized.
    """

    def render_stills(self, brief: PostBrief) -> dict:
        """Generate the hero + per-shot stills. Return a ``RenderResult`` dict with
        ``status="stills_ready"`` (or ``placeholder``/``error``)."""
        ...

    def regenerate_stills(
        self, brief: PostBrief, stills: dict, indices: list[int], prompt_overrides: dict[int, str]
    ) -> dict:
        """Re-generate the stills for ``indices`` (with optional per-shot prompt overrides), reusing
        the prior ``stills`` result for the untouched shots. Return an updated ``RenderResult`` dict."""
        ...
