"""Application settings (pydantic-settings).

Everything that varies between runs lives here, loaded from the environment with the
`NORA_` prefix (and an optional `.env`). The model layer is provider-agnostic: the
`model` / `router_model` / `embedding_model` fields are `provider:model` config strings
fed to `init_chat_model` / `init_embeddings`, so switching OpenAI -> Anthropic is an env
change, not a code change.

No secret ever lives here. Provider keys (`OPENAI_API_KEY`, ...) and LangSmith tracing
(`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, ...) are read straight from the environment by
the integration packages — they are intentionally *not* Settings fields.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# The bundled DB lives next to this package, so the default path is correct no matter
# what the current working directory is (avoids the "frozen at import / cwd-dependent"
# class of bug this project is teaching against).
_PACKAGE_DIR = Path(__file__).resolve().parent
_DEFAULT_DB_PATH = _PACKAGE_DIR / "data" / "curry_nomad.db"
# The operations capability owns a *writable* SQLite DB, kept separate from the read-only
# bundled `curry_nomad.db` so the committed dataset stays pristine and deterministic. It lives
# in a gitignored `data/runtime/` dir (package-relative, so it's cwd-independent like the DB
# above) and is (re)built by `python -m nora.operations.seed`.
_DEFAULT_OPS_DB_PATH = _PACKAGE_DIR / "data" / "runtime" / "operations.db"


class Settings(BaseSettings):
    """Typed, env-driven configuration. `get_settings()` returns a cached singleton."""

    model_config = SettingsConfigDict(
        env_prefix="NORA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Model layer (provider-agnostic config strings) ---
    model: str = "openai:gpt-4o"  # main reasoning model
    router_model: str = "openai:gpt-4o-mini"  # cheap classifier
    embedding_model: str = "openai:text-embedding-3-small"  # Store index embedder
    embedding_dims: int = 1536  # must match the embedding model

    # --- Data ---
    db_path: Path = _DEFAULT_DB_PATH
    ops_db_path: Path = _DEFAULT_OPS_DB_PATH  # writable operations DB (NORA_OPS_DB_PATH)
    data_as_of: date = date(2026, 6, 30)  # fixed "today" for deterministic time queries

    # --- Analytics tool guards ---
    max_sql_rows: int = 200  # LIMIT cap injected into run_sql
    sql_timeout_s: float = 5.0  # statement timeout

    # --- Marketing workflow knobs ---
    marketing_max_revisions: int = 2  # evaluator-optimizer loop bound
    marketing_num_concepts: int = 3  # parallel ideation count

    # --- Rendering adapter ---
    renderer: Literal["placeholder", "openrouter"] = "placeholder"
    openrouter_api_key: str | None = None  # only used by the openrouter renderer
    openrouter_video_model: str = Field(
        default="",  # TODO: set when OpenRouter text-to-video is wired (M7)
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return Settings()
