"""Operations — Nora's deterministic inventory + orders + delivery-routing system.

Phase 1 is intentionally **non-agentic**: a real operations backend (a writable store, pure
service functions that own every business invariant, a deterministic route optimizer, and a
small REST API the web `/inventory` page calls). No LLM touches any of it.

That is the point. By building the deterministic system first, the *limits of agentic
development* become structural rather than a lecture: in Phase 2 the agent becomes a mere caller
of these same services, so it literally cannot oversell (``create_order`` rejects it) and cannot
invent a route (``plan_route`` is a function it invokes). The agent owns language and
orchestration; this package owns computation and correctness.

Public surface used by the REST API (and, later, the agent tools):
"""

from __future__ import annotations

from nora.operations.errors import OperationsError
from nora.operations.models import (
    LedgerEntry,
    Order,
    OrderItem,
    RoutePlan,
    RouteStop,
    StockRow,
    as_dict,
)
from nora.operations.store import SqliteOperationsStore, build_operations_store

__all__ = [
    "OperationsError",
    "SqliteOperationsStore",
    "build_operations_store",
    "StockRow",
    "LedgerEntry",
    "Order",
    "OrderItem",
    "RoutePlan",
    "RouteStop",
    "as_dict",
]
