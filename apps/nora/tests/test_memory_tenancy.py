"""Tenancy tests for the two-tier long-term memory (global + per-user).

The load-bearing one is `test_resolve_user_id_ignores_client_supplied_user_id` (and its
`remember_user` sibling): the per-user namespace must be built ONLY from the server-injected auth
identity, never from a client-controlled `configurable.user_id`. On the platform the in-graph store
is raw and unscoped, so this discipline — not the framework — is the isolation control. If these go
red, per-user memory can leak across operators.

All offline: an `InMemoryStore` (no index needed — namespace filtering is what isolates) and a fake
auth-user object standing in for what Aegra injects at `configurable.langgraph_auth_user`.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from langgraph.store.memory import InMemoryStore

from nora.memory import (
    GLOBAL_OPERATIONS,
    MEMORY_TOOLS,
    global_ns,
    propose_global,
    recall,
    remember_user,
    resolve_user_id,
    user_ns,
    write_global,
)


@dataclass
class _AuthUser:
    """Stands in for the User object Aegra hard-sets at configurable.langgraph_auth_user."""

    identity: str


def _config(identity: str | None, *, spoof_user_id: str | None = None) -> dict:
    """A run config as the graph sees it. `identity` → the server-injected auth object;
    `spoof_user_id` → a client-supplied configurable.user_id an attacker might inject."""
    configurable: dict = {"thread_id": "t-1"}
    if identity is not None:
        configurable["langgraph_auth_user"] = _AuthUser(identity)
    if spoof_user_id is not None:
        configurable["user_id"] = spoof_user_id
    return {"configurable": configurable}


# --- Namespace scheme ---------------------------------------------------------------------


def test_namespace_builders():
    assert global_ns("brand") == ("global", "brand")
    assert user_ns("alice", "facts") == ("users", "alice", "facts")


def test_user_ns_refuses_empty_identity():
    with pytest.raises(ValueError):
        user_ns("")


# --- resolve_user_id ----------------------------------------------------------------------


def test_resolve_user_id_from_auth_object():
    assert resolve_user_id(_config("alice@example.com")) == "alice@example.com"


def test_resolve_user_id_none_without_identity():
    assert resolve_user_id(None) is None
    assert resolve_user_id({}) is None
    assert resolve_user_id({"configurable": {"thread_id": "t"}}) is None


def test_resolve_user_id_treats_anonymous_as_no_user():
    # The keyless (noop) fallback identity must NOT get a real namespace.
    assert resolve_user_id(_config("anonymous")) is None


def test_resolve_user_id_ignores_client_supplied_user_id():
    """THE spoof guard. An authenticated caller who injects configurable.user_id must not be able to
    redirect identity: the auth object wins, and a bare client user_id with no auth object is ignored."""
    # Authenticated as alice, but the body forges user_id=bob → still alice.
    assert resolve_user_id(_config("alice", spoof_user_id="bob")) == "alice"
    # Only a client user_id, no server-injected auth object → no identity at all (not "bob").
    assert resolve_user_id({"configurable": {"user_id": "bob"}}) is None


# --- Per-user write/read isolation --------------------------------------------------------


def test_remember_and_recall_roundtrip():
    store = InMemoryStore()
    assert remember_user(store, _config("alice"), "currency", {"text": "prefers USD"}) is True
    hits = recall(store, _config("alice"), "currency")
    assert any("USD" in str(getattr(h, "value", "")) for h in hits["user"])


def test_recall_is_isolated_across_users():
    store = InMemoryStore()
    remember_user(store, _config("alice"), "currency", {"text": "alice prefers USD"})
    bob_hits = recall(store, _config("bob"), "currency")
    assert bob_hits["user"] == []  # bob cannot see alice's private memory


def test_remember_user_noop_without_identity():
    store = InMemoryStore()
    assert remember_user(store, _config(None), "x", {"text": "y"}) is False
    # Nothing was written anywhere under users/.
    assert store.search(("users",), query="y") == []


def test_remember_user_ignores_spoofed_user_id():
    """Even with a forged configurable.user_id=bob, an alice-authenticated write lands in ALICE's
    namespace — bob's namespace stays empty."""
    store = InMemoryStore()
    remember_user(store, _config("alice", spoof_user_id="bob"), "k", {"text": "secret"})
    assert store.search(user_ns("alice", "facts"), query="secret")  # written under alice
    assert store.search(user_ns("bob", "facts"), query="secret") == []  # NOT under the forged id


# --- Global tier: gated write -------------------------------------------------------------


def test_write_global_requires_authorization():
    store = InMemoryStore()
    with pytest.raises(PermissionError):
        write_global(store, "policy", {"text": "x"})  # authorized defaults to False


def test_write_global_authorized_writes_to_global_tier():
    store = InMemoryStore()
    write_global(store, "policy", {"text": "ship within 48h"}, authorized=True)
    assert store.search(GLOBAL_OPERATIONS, query="ship")


# --- Guardrails: agent tool surface -------------------------------------------------------


def test_agent_memory_tools_exclude_global_writers():
    names = {t.name for t in MEMORY_TOOLS}
    assert names == {"save_memory", "search_memory"}
    # write_global / propose_global are functions, never agent tools.
    assert "write_global" not in names
    assert "propose_global" not in names


def test_propose_global_is_dormant_but_isolated():
    """Not an agent tool; when called directly a candidate lands in the PROPOSER's own namespace
    (auto-isolated pre-review) with provenance."""
    store = InMemoryStore()
    assert propose_global(store, _config("alice"), "idea", {"text": "global?"}, reason="seen twice")
    items = store.search(user_ns("alice", "global_candidate"), query="global")
    assert items and items[0].value["_proposed_by"] == "alice"
    assert items[0].value["_status"] == "pending"
