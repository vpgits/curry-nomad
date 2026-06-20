"""Memory wiring: short-term (checkpointer) + long-term (semantic Store).

Both are real and actually read in nodes — the contrast with the "store built but never
compiled into the graph" anti-pattern is one of the lessons.

  - Checkpointer (InMemorySaver): per-thread state + the mechanism that makes
    `interrupt()`/resume work. Production swap: SqliteSaver / PostgresSaver (config-only).
  - Store (InMemoryStore with semantic index): cross-thread business knowledge. Two
    namespaces — brand voice (used by marketing) and metric definitions (used by analytics).
    Production swap: PostgresStore / RedisStore.

Nodes read memory via the injected runtime: `runtime.store.search(NAMESPACE, query=..., limit=3)`.
"""

from __future__ import annotations

from langchain.embeddings import init_embeddings
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from nora.config import Settings

# Namespaces are tuples of strings (folder-like). Cross-thread / persistent.
BRAND = ("curry_nomad", "brand")
DEFINITIONS = ("curry_nomad", "definitions")


def build_store(settings: Settings) -> InMemoryStore:
    """Build the long-term Store with a semantic index over the `text` field (and `$`,
    the whole value), embedded with the configured embedding model."""
    return InMemoryStore(
        index={
            "embed": init_embeddings(settings.embedding_model),
            "dims": settings.embedding_dims,
            "fields": ["text", "$"],
        }
    )


def build_checkpointer() -> InMemorySaver:
    """Build the short-term checkpointer. Required for HITL interrupts + resume."""
    return InMemorySaver()


# The seed knowledge. Kept as data so the demo can point at exactly what shapes behavior.
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


def seed_brand_knowledge(store: InMemoryStore) -> None:
    """Idempotently load brand voice + metric definitions into the Store. Called once at
    startup so both capabilities can retrieve them by semantic search."""
    for key, value in _BRAND_KNOWLEDGE:
        store.put(BRAND, key, value)
    for key, value in _DEFINITIONS_KNOWLEDGE:
        store.put(DEFINITIONS, key, value)
