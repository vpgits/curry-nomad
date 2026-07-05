"""Memory wiring: short-term (checkpointer) + long-term (semantic Store).

Both are real and actually read in nodes — the contrast with the "store built but never
compiled into the graph" anti-pattern is one of the lessons.

  - Checkpointer (InMemorySaver): per-thread state + the mechanism that makes
    `interrupt()`/resume work. Production swap: SqliteSaver / PostgresSaver (config-only).
  - Store (InMemoryStore with semantic index): long-term knowledge, in TWO tiers:
      * GLOBAL  — shared across every operator (brand voice, metric definitions, ops facts).
                  Seeded / admin-written only; the agent never writes it (poisoning + reverse-leak
                  surface). Rooted at ("global", ...).
      * PER-USER — private to one operator (their facts, preferences). The agent writes these
                  freely via a tool; blast radius is one user. Rooted at ("users", <user_id>, ...)
                  — the SAME subtree Aegra's REST store scoping produces, so the two are one space.
    Production swap: PostgresStore / RedisStore.

Nodes read memory via the injected runtime: `runtime.store.search(NAMESPACE, query=..., limit=3)`.

**The safety invariant (this is the actual isolation control, in place of RLS).** On the platform
the in-graph store is the RAW, unscoped `AsyncPostgresStore` — LangGraph/Aegra do NOT namespace what
the graph reads/writes. So a per-user namespace prefix is only ever built from the SERVER-INJECTED
identity (`resolve_user_id`), never from a client-influenced value, and `search` never stops at the
bare ("users",) root. See `resolve_user_id` for why we read `langgraph_auth_user`, not
`configurable.user_id`.
"""

from __future__ import annotations

from typing import Any

from langchain.embeddings import init_embeddings
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.config import get_config, get_store
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from nora.config import Settings
from nora.observability import get_logger
from nora.schemas import (
    ConceptIdea,
    Critique,
    PostBrief,
    RouteDecision,
    Shot,
    ShotPrompt,
)

log = get_logger(__name__)


# --- Namespace scheme (two tiers) -----------------------------------------------------------
# Namespaces are tuples of strings (folder-like), stored as a dot-joined `prefix` in Postgres.
# GLOBAL sits at its own root, structurally distinct from the per-user tree so a search can never
# accidentally cross tiers. "global" and "users" are RESERVED — a real user identity must never
# collide with them (they never can: identities are emails / oauth subs, not these literals).
GLOBAL_ROOT = "global"
USER_ROOT = "users"


def global_ns(*parts: str) -> tuple[str, ...]:
    """A shared-across-all-operators namespace. Seeded / admin-written only (never agent-written)."""
    return (GLOBAL_ROOT, *parts)


def user_ns(user_id: str, *parts: str) -> tuple[str, ...]:
    """A per-operator namespace. `user_id` MUST come from `resolve_user_id` (the server-injected
    identity) — never a client-supplied value. Refuse to build one without an identity, so a missing
    id can never silently root a write at a shared/global prefix."""
    if not user_id:
        raise ValueError("refusing to build a user namespace without an identity")
    return (USER_ROOT, user_id, *parts)


# Global tiers the read path searches. `("global", ...)` — NOT ("curry_nomad", ...): the seed
# (scripts/seed_global.py) writes these via the RAW store, so the in-graph raw reads line up. (The
# old REST-seeded ("curry_nomad", ...) landed under ["users", <id>, ...] and never matched — the
# seed/read mismatch this fixes.)
GLOBAL_BRAND = global_ns("brand")
GLOBAL_DEFINITIONS = global_ns("definitions")
GLOBAL_OPERATIONS = global_ns("operations")


# --- The identity resolver (THE security choke point) ---------------------------------------
def resolve_user_id(config: dict | None) -> str | None:
    """The server-injected operator identity, or None when there isn't one.

    Reads `configurable.langgraph_auth_user` — the ONLY server-authoritative source. Aegra hard-sets
    it to the authenticated user object on every run (langgraph_service.inject_user_context), so a
    client cannot forge it. We deliberately do NOT read `configurable.user_id`: Aegra fills that with
    `setdefault` and does not pin it, so a client body carrying `configurable.user_id` survives and
    would let an authenticated caller point per-user memory at ANOTHER operator's namespace. Reading
    the auth object's `.identity` closes that spoof vector — this is the safety invariant.

    Returns None when there is no real identity (no auth object, or the keyless `anonymous` fallback).
    Callers MUST treat None as "no per-user memory", never as a shared-namespace fallback."""
    cfg = (config or {}).get("configurable", {}) if config else {}
    auth_user = cfg.get("langgraph_auth_user")
    if auth_user is None:
        return None
    # Aegra sets a User object (has `.identity`); tolerate a dict too (defensive).
    identity = getattr(auth_user, "identity", None)
    if identity is None and isinstance(auth_user, dict):
        identity = auth_user.get("identity")
    if not identity or identity == "anonymous":
        return None
    return identity


# --- Read path: search both tiers, labelled distinctly --------------------------------------
def recall(store: BaseStore, config: dict | None, query: str, *, limit: int = 3) -> dict[str, list]:
    """Search GLOBAL (shared) and PER-USER (private) memory for `query`, returned as two labelled
    lists so a caller/model can apply precedence (user overrides global for personalization; global
    definitions stay canonical). Per-user search is skipped entirely when there is no verified
    identity (`resolve_user_id` → None), so it can never fall back to a shared bucket."""
    out: dict[str, list] = {"global": [], "user": []}
    for namespace in (GLOBAL_BRAND, GLOBAL_DEFINITIONS, GLOBAL_OPERATIONS):
        out["global"].extend(store.search(namespace, query=query, limit=limit))
    uid = resolve_user_id(config)
    if uid:
        for category in ("facts", "preferences"):
            out["user"].extend(store.search(user_ns(uid, category), query=query, limit=limit))
    return out


# --- Prompt-injection helpers: fold recalled memory into ANY node's system prompt -----------
# Analytics folds `global.definitions` and marketing folds `global.brand` into their prompts by hand
# (each searches the ONE namespace it needs). These give the SAME retrieval a reusable, node-agnostic
# shape so the supervisor and workspace agent can be memory-aware too — searching every tier and
# formatting a compact block. Both are best-effort (return None/"" on any failure) so a memory hiccup
# never crashes a turn.
def current_store() -> BaseStore | None:
    """The store configured for THIS graph run (runtime-injected on the platform, build-time in the
    CLI/tests), or None when there isn't one. `get_store()` raises outside a run / with no store, so a
    node folding memory into its prompt degrades to "no memory" instead of crashing."""
    try:
        return get_store()
    except Exception:  # noqa: BLE001
        return None


def current_config() -> dict | None:
    """The run config for THIS graph step (carries the server-injected `langgraph_auth_user`), or
    None. Best-effort like `current_store`, so a node can resolve per-user memory without threading
    `config` through its signature."""
    try:
        return get_config()
    except Exception:  # noqa: BLE001
        return None


def recall_block(
    store: BaseStore | None,
    config: dict | None,
    query: str,
    *,
    limit: int = 3,
    header: str = "Relevant long-term memory",
) -> str:
    """Format `recall()` hits into a compact prompt block — shared (global) knowledge plus THIS
    operator's saved context — or "" when there's nothing (or no store). A node folds the result into
    its system prompt so global brand/definitions and per-user preferences shape behaviour. Empty
    store / no hits / no identity all collapse to "" (the caller appends only when truthy), so a graph
    with no seeded memory or no signed-in operator behaves exactly as before."""
    if store is None:
        return ""
    try:
        hits = recall(store, config, query, limit=limit)
    except Exception:  # noqa: BLE001 — memory is best-effort; never break a turn
        return ""
    shared = [t for t in (_item_text(i) for i in hits["global"]) if t]
    user = [t for t in (_item_text(i) for i in hits["user"]) if t]
    if not shared and not user:
        return ""
    lines = [f"{header}:"]
    if shared:
        lines.append("Shared knowledge (Curry Nomad):")
        lines.extend(f"- {t}" for t in shared)
    if user:
        lines.append("This operator's saved context (their preferences override shared defaults):")
        lines.extend(f"- {t}" for t in user)
    return "\n".join(lines)


# --- Write paths (asymmetric: per-user is free, global is gated) ----------------------------
def remember_user(
    store: BaseStore, config: dict | None, key: str, value: dict, *, category: str = "facts"
) -> bool:
    """Write to the CURRENT operator's private memory. No-op (returns False) when there is no verified
    identity — never falls back to a shared namespace. Safe to expose as a free agent tool: worst case
    a user corrupts their own context (blast radius = one user)."""
    uid = resolve_user_id(config)
    if uid is None:
        return False
    store.put(user_ns(uid, category), key, value)
    log.info("memory.user_write", category=category, key=key)
    return True


def write_global(
    store: BaseStore, key: str, value: dict, *, category: str = "operations", authorized: bool = False
) -> None:
    """Write to GLOBAL memory (visible to EVERY operator). Off by default — this is the
    memory-poisoning / reverse-leak surface, so it is gated behind an explicit `authorized=True` and
    is NOT exposed as an agent tool. Called only by an admin script or a reviewed promotion flow."""
    if not authorized:
        raise PermissionError("global writes must be explicitly authorized")
    store.put(global_ns(category), key, value)
    log.info("memory.global_write", category=category, key=key)


def propose_global(
    store: BaseStore, config: dict | None, key: str, value: dict, *, reason: str = ""
) -> bool:
    """DORMANT accumulation seam — the activation point for "Nora proposes a global fact, a human
    approves it later" (out-of-loop review queue). NOT wired as an agent tool and there is NO review
    UI yet; do not register it. Activate only when curated-global proves you're repeatedly hand-adding
    the same kind of fact (see the tenancy design doc). Reviewer identity is coupled to the (deferred)
    org/role tier.

    A candidate lands in the PROPOSER's own per-user namespace, so an un-reviewed candidate is already
    correctly isolated (only that user sees it until a human promotes it via `write_global`). The
    `_proposed_by` / `_reason` provenance is what the reviewer needs to judge it."""
    uid = resolve_user_id(config)
    if uid is None:
        return False
    store.put(
        user_ns(uid, "global_candidate"),
        key,
        {**value, "_proposed_by": uid, "_reason": reason, "_status": "pending"},
    )
    return True


# --- Agent tools: per-user write + recall ONLY (guardrail: never write_global/propose_global) ---
# Bound onto the analytics agent (see analytics/graph.py). They reach the runtime store + config via
# LangGraph's `get_store()` / `get_config()`, so `resolve_user_id` sees the server-injected identity.
# Both degrade to a friendly message (never raise) so ToolNode's narrow SqlError handler stays narrow.
@tool
def save_memory(key: str, value: str) -> str:
    """Save a durable fact or preference about the CURRENT operator to their private long-term memory
    (persists across conversations). Use for things like "prefers revenue in USD" or "manages the
    Jaffna warehouse". `key` is a short stable slug (e.g. "preferred_currency"); `value` is the fact
    in plain words."""
    try:
        ok = remember_user(get_store(), get_config(), key, {"text": value})
    except Exception as exc:  # noqa: BLE001 — a memory hiccup must never crash the turn
        log.info("memory.save_failed", error=str(exc))
        return "I couldn't save that just now."
    return (
        f"Saved to your memory: {key}."
        if ok
        else "I can't save personal memory in this session (no signed-in operator)."
    )


@tool
def search_memory(query: str) -> str:
    """Search YOUR (the current operator's) saved memory plus Curry Nomad's shared knowledge for
    context relevant to `query`. Returns saved facts/preferences and shared brand/metric knowledge."""
    try:
        hits = recall(get_store(), get_config(), query)
    except Exception as exc:  # noqa: BLE001
        log.info("memory.search_failed", error=str(exc))
        return "I couldn't search memory just now."
    lines: list[str] = []
    user_hits = [_item_text(i) for i in hits["user"]]
    global_hits = [_item_text(i) for i in hits["global"]]
    if user_hits:
        lines.append("[Your saved context]\n" + "\n".join(f"- {t}" for t in user_hits if t))
    if global_hits:
        lines.append("[Shared knowledge]\n" + "\n".join(f"- {t}" for t in global_hits if t))
    return "\n\n".join(lines) if lines else "No relevant saved context found."


def _item_text(item: Any) -> str:
    """Best-effort text of a store search hit (its value's `text`, else the whole value)."""
    value = getattr(item, "value", None)
    if isinstance(value, dict):
        return str(value.get("text") or value)
    return str(value)


MEMORY_TOOLS = [save_memory, search_memory]


# --- Store / checkpointer construction ------------------------------------------------------
def build_store(settings: Settings) -> InMemoryStore:
    """Build the long-term Store with a semantic index over the `text` field (and `$`,
    the whole value), embedded with the configured embedding model. Index config MUST match
    `aegra.json` (and `scripts/seed_global.py`) so vectors are comparable across paths."""
    return InMemoryStore(
        index={
            "embed": init_embeddings(settings.embedding_model),
            "dims": settings.embedding_dims,
            "fields": ["text", "$"],
        }
    )


# Our structured-output schemas. Graph state stores their `.model_dump()` dicts (see
# nora/state.py), so the checkpointer normally never sees these types. This allow-list is
# belt-and-suspenders for the CLI path: if a Pydantic value ever reaches the checkpointer
# (now, or via a future change), it still round-trips as the real model — even under
# `LANGGRAPH_STRICT_MSGPACK=true`, where unregistered types silently degrade to bare dicts.
# NOTE: this only covers the checkpointer *we* construct. On the platform path
# (Aegra) the server builds its own serializer, so the JSON-native-state design in
# nora/state.py — not this list — is what keeps persistence portable there.
_NORA_MSGPACK_SCHEMAS = [
    RouteDecision, ConceptIdea, Shot, ShotPrompt, Critique, PostBrief,
]


def build_checkpointer() -> InMemorySaver:
    """Build the short-term checkpointer. Required for HITL interrupts + resume."""
    return InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=_NORA_MSGPACK_SCHEMAS))


# --- Seed knowledge (GLOBAL tier) -----------------------------------------------------------
# Kept as data so the demo can point at exactly what shapes behavior. Written to the GLOBAL
# namespaces both in-process (CLI, `seed_brand_knowledge`) and on the platform via the RAW store
# (`scripts/seed_global.py`) — the same namespaces the graph reads.
_BRAND_KNOWLEDGE: list[tuple[str, dict]] = [
    (
        "voice",
        {
            "text": "Curry Nomad's brand voice is warm, a little cheeky, and proudly Sri "
            "Lankan. Celebrate origin and authenticity (single-estate spices, real "
            "places like Matale and Jaffna). Never generic AI ad copy; never medical claims."
        },
    ),
    (
        "audience",
        {
            "text": "We speak to home cooks and diaspora foodies who care where their "
            "spices come from and want bold, honest flavor — not supermarket blends."
        },
    ),
]

_DEFINITIONS_KNOWLEDGE: list[tuple[str, dict]] = [
    (
        "revenue",
        {
            "text": "revenue = sum(order_items.quantity * order_items.unit_price_lkr) for "
            "orders whose status is not 'cancelled', net of refunds (subtract refunds.amount_lkr)."
        },
    ),
    (
        "week_start",
        {"text": "A week starts on Monday when grouping orders by week."},
    ),
    (
        "active_product",
        {"text": "An active product has products.active = 1."},
    ),
]


def seed_items() -> list[tuple[tuple[str, ...], str, dict]]:
    """The (namespace, key, value) GLOBAL seed records, shared by the in-process seeder
    (`seed_brand_knowledge`, CLI) and the platform seed script (`scripts/seed_global.py`, which writes
    them straight to the raw Postgres store)."""
    return [(GLOBAL_BRAND, key, value) for key, value in _BRAND_KNOWLEDGE] + [
        (GLOBAL_DEFINITIONS, key, value) for key, value in _DEFINITIONS_KNOWLEDGE
    ]


def seed_brand_knowledge(store: BaseStore) -> None:
    """Idempotently load brand voice + metric definitions into the GLOBAL tier. Called once at
    startup (CLI) so both capabilities can retrieve them by semantic search."""
    for namespace, key, value in seed_items():
        store.put(namespace, key, value)
