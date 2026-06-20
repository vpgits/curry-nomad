"""Tests for the analytics @tool wrappers (M1).

These run against the committed bundled DB via the module-level SpiceDB.
"""

from __future__ import annotations

import pytest

from nora.analytics.tools import describe_table, list_tables, run_sql
from nora.services.interfaces import SqlError


def test_list_tables_tool():
    out = list_tables.invoke({})
    assert "products" in out and "orders" in out


def test_describe_table_tool():
    out = describe_table.invoke({"table": "products"})
    assert "unit_price_lkr" in out
    assert "Sample rows" in out


def test_run_sql_tool_returns_formatted_rows():
    out = run_sql.invoke({"query": "SELECT COUNT(*) AS n FROM products"})
    assert "n" in out
    assert "18" in out
    assert "row(s)" in out


def test_run_sql_tool_propagates_sqlerror_on_bad_sql():
    # The tool must NOT swallow the error — the graph's ToolNode converts it to a ToolMessage.
    with pytest.raises(SqlError):
        run_sql.invoke({"query": "SELECT bogus_col FROM products"})


def test_run_sql_tool_rejects_writes():
    with pytest.raises(SqlError):
        run_sql.invoke({"query": "DELETE FROM products"})
