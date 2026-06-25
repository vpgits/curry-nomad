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
# Generated marketing media (hero image, per-shot stills) lands here when the OpenRouter renderer
# runs. Package-relative (cwd-independent) and gitignored like the runtime ops DB; the nora renderer
# writes it and the ops-api serves it at /media (same repo locally; a shared volume in Docker).
_DEFAULT_MEDIA_DIR = _PACKAGE_DIR / "data" / "runtime" / "media"


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
    # Optional Anthropic extended-thinking budget for the analytics agent (NORA_THINKING_BUDGET).
    # 0 = off (the default keeps gpt-4o behaviour unchanged). When > 0 *and* the analytics model is
    # an Anthropic one, the agent enables extended thinking with this token budget, so its reasoning
    # chain streams into the chat as `thinking` content blocks (see analytics/graph.py). Other
    # providers (e.g. OpenAI gpt-4o) ignore it — they don't emit visible reasoning.
    thinking_budget: int = 0

    # --- Data ---
    db_path: Path = _DEFAULT_DB_PATH
    ops_db_path: Path = _DEFAULT_OPS_DB_PATH  # writable operations DB (NORA_OPS_DB_PATH)
    data_as_of: date = date(2026, 6, 30)  # fixed "today" for deterministic time queries

    # --- Operations service ---
    # The routing capability plans a delivery route by calling the ops API (the same service the web
    # app uses), so the writable ops DB stays single-owner. Override with NORA_OPS_API_URL.
    ops_api_url: str = "http://localhost:8000"

    # --- Google Workspace capability (optional; OFF by default) ---
    # The `workspace` capability is an agent that acts on the logged-in operator's own Google account
    # (Gmail/Calendar) through the self-hosted Google Workspace MCP server. It's gated OFF so the base
    # install stays dependency-light (no langchain-mcp-adapters) and the offline suite/teaching paths
    # are untouched; turn it on with NORA_WORKSPACE_ENABLED=true (and run `uv sync --extra workspace`).
    # Secrets (Google OAuth client id/secret, NEXTAUTH_SECRET) are NOT Settings fields — they're read
    # from the environment by the web layer + the Aegra auth handler, like every other provider key.
    workspace_enabled: bool = False  # master flag (NORA_WORKSPACE_ENABLED)
    workspace_mcp_url: str = "http://localhost:8001"  # the MCP server's streamable-http endpoint
    # Informational echo of the scopes the demo grants; the real enforcement is the MCP server's
    # `--permissions` flag (and the OAuth consent the operator approves).
    workspace_permissions: str = "gmail:send docs:full sheets:full tasks:full drive:readonly"

    # --- Analytics tool guards ---
    max_sql_rows: int = 200  # LIMIT cap injected into run_sql
    sql_timeout_s: float = 5.0  # statement timeout

    # --- Marketing workflow knobs ---
    marketing_max_revisions: int = 2  # evaluator-optimizer loop bound
    marketing_num_concepts: int = 3  # parallel ideation count

    # --- Rendering adapter ---
    # Placeholder by default (no external calls, no spend). Switch to the real OpenRouter renderer
    # with NORA_RENDERER=openrouter + an OPENROUTER_API_KEY. Every model/knob below is overridable.
    renderer: Literal["placeholder", "openrouter"] = "placeholder"
    openrouter_api_key: str | None = None  # OPENROUTER_API_KEY; only used by the openrouter renderer
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Cheapest-tier defaults (see the OpenRouter model lists). Image gen is synchronous; video is an
    # async job (submit → poll). Both are `provider/model` ids on OpenRouter, not init_chat_model strings.
    openrouter_image_model: str = "black-forest-labs/flux.2-flex"
    openrouter_video_model: str = "google/veo-3.1-lite"
    # Per-shot render knobs. Reels are vertical; keep duration/resolution small to bound spend.
    render_aspect_ratio: str = "9:16"  # instagram_reel
    render_resolution: str = "720p"
    render_video_duration_s: int = 6
    render_generate_audio: bool = False  # audio adds cost/latency; off for the demo
    render_max_shots: int = 4  # cap the number of shots rendered (cost guard)
    # Where generated images are written, and the PUBLIC base URL OpenRouter can fetch them from for
    # image→video first-frame conditioning. Unset (the local default) → the renderer falls back to
    # text→video, since OpenRouter can't reach a localhost media URL.
    media_dir: Path = _DEFAULT_MEDIA_DIR
    media_public_base_url: str | None = None  # e.g. an ngrok/deploy origin that serves /media


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return Settings()
