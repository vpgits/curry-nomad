"""Shared pytest fixtures.

`seeded_db` builds the deterministic Curry Nomad database into a temp dir once per session,
so DB-backed tests run against real (but disposable) data without touching the committed file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nora.data import seed
from nora.services.spice_db import SqliteSpiceDB


@pytest.fixture(scope="session")
def seeded_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    db_path = tmp_path_factory.mktemp("data") / "curry_nomad.db"
    seed.build(db_path)
    return db_path


@pytest.fixture
def spice_db(seeded_db: Path) -> SqliteSpiceDB:
    return SqliteSpiceDB(seeded_db, max_sql_rows=200, sql_timeout_s=5.0)
