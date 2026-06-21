"""Seed the platform's semantic Store with Curry Nomad's brand voice + metric definitions.

Run this once after Aegra is up, so the analytics agent can retrieve metric definitions and the
marketing workflow can retrieve brand voice (memory shaping behavior):

    uv run --extra aegra aegra dev                   # in one terminal (serves the graph on :2026)
    uv run python apps/nora/scripts/seed_store.py   # in another (writes the seed over the Store API)

Targets http://localhost:2026 by default (Aegra). Override with --url or NORA_API_URL — the same
script works against any Agent-Protocol server.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from langgraph_sdk import get_client  # noqa: E402

from nora.memory import seed_items  # noqa: E402


async def seed(url: str) -> None:
    client = get_client(url=url)
    for namespace, key, value in seed_items():
        # `namespace` is positional-only in langgraph-sdk's StoreClient.put_item().
        await client.store.put_item(list(namespace), key=key, value=value)
        print(f"seeded {namespace} / {key}")
    print(f"Done. Seeded {len(seed_items())} items into {url}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the platform's semantic Store.")
    parser.add_argument("--url", default=os.getenv("NORA_API_URL", "http://localhost:2026"))
    asyncio.run(seed(parser.parse_args().url))


if __name__ == "__main__":
    main()
