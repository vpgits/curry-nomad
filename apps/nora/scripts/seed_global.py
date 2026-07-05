"""Seed the GLOBAL tier of long-term memory (brand voice + metric definitions).

Writes straight to the RAW Postgres store — NOT through Aegra's REST Store API. This is deliberate
and load-bearing: the REST API rewrites every namespace under `["users", <id>, ...]` (its per-user
scoping), so a REST seed of `("global", "brand")` would land at `["users", <id>, "global", "brand"]`
and the graph's raw in-graph read of `("global", "brand")` would never find it (the seed/read
mismatch this fixes). By connecting to the same Postgres directly, the seed lands at the exact
`global.*` prefixes the graph reads.

Run once against the SAME Postgres Aegra uses:

    # local dev (aegra dev manages a localhost:5432 pgvector container):
    uv run --extra aegra python apps/nora/scripts/seed_global.py

    # containers: the compose `seed` one-shot runs this with DATABASE_URL set to the postgres service.

Connection: --url, else $DATABASE_URL, else built from $POSTGRES_* (localhost defaults). Needs
OPENAI_API_KEY (the store embeds each value at write time, with the SAME model as aegra.json, so the
vectors are comparable to what the running graph queries against).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Load the repo-root .env so a standalone `uv run` of this script sees OPENAI_API_KEY. The store's
# embedder reads that key straight from the environment (it's deliberately NOT a Settings field, and
# neither `uv run` nor pydantic-settings export it), so without this the embed init dies with
# `OpenAIError: Missing credentials`. Guarded + override=False: a no-op if python-dotenv is missing,
# and a real env var (docker/compose/aegra) always wins over the file.
try:
    from dotenv import load_dotenv  # noqa: E402

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
except ImportError:
    pass

from langchain.embeddings import init_embeddings  # noqa: E402

from nora.config import get_settings  # noqa: E402
from nora.memory import seed_items  # noqa: E402


def _resolve_db_uri(cli_url: str | None) -> str:
    """--url > $DATABASE_URL > built from $POSTGRES_* (localhost defaults, matching aegra dev)."""
    if cli_url:
        return cli_url
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    user = os.getenv("POSTGRES_USER", "aegra")
    password = os.getenv("POSTGRES_PASSWORD", "aegra")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "aegra")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


async def seed(uri: str) -> None:
    # Lazy import: the postgres store deps ship with the `aegra` extra, so merely having this script
    # on disk never burdens the base/offline install.
    from langgraph.store.postgres import AsyncPostgresStore

    settings = get_settings()
    index = {
        "embed": init_embeddings(settings.embedding_model),  # MUST match aegra.json's embed model
        "dims": settings.embedding_dims,
        "fields": ["text", "$"],
    }
    async with AsyncPostgresStore.from_conn_string(uri, index=index) as store:
        await store.setup()  # idempotent DDL (store + store_vectors + pgvector extension)
        items = seed_items()
        for namespace, key, value in items:
            await store.aput(namespace, key, value)
            print(f"seeded {'.'.join(namespace)} / {key}")
        print(f"Done. Seeded {len(items)} GLOBAL items into {uri.rsplit('@', 1)[-1]}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the GLOBAL tier of the long-term Store.")
    parser.add_argument("--url", default=None, help="Postgres URI (else $DATABASE_URL / $POSTGRES_*)")
    asyncio.run(seed(_resolve_db_uri(parser.parse_args().url)))


if __name__ == "__main__":
    main()
