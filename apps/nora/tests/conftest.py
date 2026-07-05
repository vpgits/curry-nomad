"""Shared pytest fixtures.

`seeded_db` builds the deterministic Curry Nomad database into a temp dir once per session,
so DB-backed tests run against real (but disposable) data without touching the committed file.
"""

from __future__ import annotations

import os
from pathlib import Path

# The offline suite has no provider keys and no MCP server. The SHIPPED defaults are now first-party
# (renderer=openrouter, workspace ON), so pin them to their offline-safe modes for the whole suite —
# tests that exercise rendering/workspace inject fakes; everything else stays placeholder +
# workspace-off (so the default orchestrator's workspace node is the sync connect-stub). setdefault
# so an explicit env still wins. Must run before the first get_settings().
os.environ.setdefault("NORA_RENDERER", "placeholder")
os.environ.setdefault("NORA_WORKSPACE_ENABLED", "false")
# Operations is ON by default (first-party) and its agent writes the on-disk ops DB in-process — pin
# it OFF for the suite so the default orchestrator uses the sync stub and no test touches the real DB;
# the operations tests set operations_enabled=True and inject a store on a disposable temp DB.
os.environ.setdefault("NORA_OPERATIONS_ENABLED", "false")

import pytest  # noqa: E402 — imported after the env pins above

from nora.config import get_settings  # noqa: E402
from nora.data import seed  # noqa: E402
from nora.services.spice_db import SqliteSpiceDB  # noqa: E402

get_settings.cache_clear()  # drop any cached settings so the env pins above take effect


@pytest.fixture(scope="session")
def seeded_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    db_path = tmp_path_factory.mktemp("data") / "curry_nomad.db"
    seed.build(db_path)
    return db_path


@pytest.fixture
def spice_db(seeded_db: Path) -> SqliteSpiceDB:
    return SqliteSpiceDB(seeded_db, max_sql_rows=200, sql_timeout_s=5.0)


@pytest.fixture
def seeded_ops_db(seeded_db: Path, tmp_path: Path) -> Path:
    """A fresh, writable operations DB per test (function-scoped — tests mutate it), built
    deterministically from the session's read-only business DB."""
    from nora.operations import seed as ops_seed

    ops_path = tmp_path / "operations.db"
    ops_seed.build(ops_path, source_db_path=seeded_db)
    return ops_path


@pytest.fixture
def ops_store(seeded_ops_db: Path):
    from nora.operations.store import SqliteOperationsStore

    return SqliteOperationsStore(seeded_ops_db)
