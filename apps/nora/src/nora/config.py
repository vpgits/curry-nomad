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

from pydantic import AliasChoices, Field
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

# Human-readable labels for the Google Workspace scopes, keyed (area, level). THE single source of
# truth for describing the workspace capability: every prompt (router instructions, the workspace
# agent's system prompt, the handoff-tool blurb) is DERIVED from `workspace_permissions` via
# `Settings.workspace_scope_summary()`, so the descriptions can't drift out of sync with the real
# grant — the staleness bug where the prompts advertised "Gmail + Calendar only" (Calendar wasn't even
# granted) while Sheets/Docs/Drive/Tasks were, so the router refused to route spreadsheet requests.
_WORKSPACE_SCOPE_LABELS: dict[tuple[str, str], str] = {
    ("gmail", "send"): "Gmail (read, draft, and send email)",
    ("gmail", "readonly"): "Gmail (read email)",
    ("sheets", "full"): "Google Sheets (read and edit — create spreadsheets, add tabs, write values)",
    ("sheets", "readonly"): "Google Sheets (read)",
    ("docs", "full"): "Google Docs (read and edit)",
    ("docs", "readonly"): "Google Docs (read)",
    ("tasks", "full"): "Google Tasks (read and manage tasks)",
    ("tasks", "readonly"): "Google Tasks (read)",
    ("drive", "full"): "Google Drive (read and write files)",
    ("drive", "readonly"): "Google Drive (read-only)",
    ("calendar", "full"): "Google Calendar (read and create/modify events)",
    ("calendar", "readonly"): "Google Calendar (read events)",
}


class Settings(BaseSettings):
    """Typed, env-driven configuration. `get_settings()` returns a cached singleton."""

    model_config = SettingsConfigDict(
        env_prefix="NORA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,  # allow constructing by field name even when a field sets a validation_alias
    )

    # --- Model layer (provider-agnostic config strings) ---
    model: str = "openai:gpt-5.4"  # main reasoning model
    router_model: str = "openai:gpt-5.4"  # cheap classifier
    # Reasoning effort for the supervisor/router model — opt-in, OpenAI gpt-5.x reasoning models only.
    # Empty (default) = off: the router stays a cheap deterministic classifier (temperature=0),
    # unchanged for the gpt-4o-mini default and every non-OpenAI provider. Set it (with
    # NORA_ROUTER_MODEL pointed at a reasoning model, e.g. `openai:gpt-5.4`) to make the router *plan*
    # its delegation with internal reasoning at this effort and emit an auto reasoning **summary** that
    # rides into the trace (`output_version="responses/v1"` → the summary lands as a `reasoning` block
    # on the model call). "medium" is the models' default level. Mirrors the analytics `thinking_budget`
    # opt-in — a separate knob because reasoning config is provider-specific. Needs an org verified with
    # OpenAI to generate summaries.
    router_reasoning_effort: Literal["", "minimal", "low", "medium", "high", "xhigh"] = ""  # NORA_ROUTER_REASONING_EFFORT
    embedding_model: str = "openai:text-embedding-3-small"  # Store index embedder
    embedding_dims: int = 1536  # must match the embedding model
    # --- Per-node model overrides (each empty by default → falls back to `model`) ---
    # Run a different model for a single capability without changing the base `model` — e.g. a strong
    # reasoning model for analytics' SQL loop, a cheap one for the dashboard card. Resolve them via
    # `model_for(node)` (below); empty = use `model`, so existing single-model setups are unchanged.
    # The SUPERVISOR is configured separately, via `router_model` above (historically the cheap
    # classifier, and the one node with its own reasoning-effort knob) — it is deliberately NOT routed
    # through `model_for`. So to run the supervisor on the strong model, set NORA_ROUTER_MODEL.
    analytics_model: str = ""  # NORA_ANALYTICS_MODEL — the analytics SQL agent (tool loop)
    marketing_model: str = ""  # NORA_MARKETING_MODEL — the marketing workflow's creative model
    workspace_model: str = ""  # NORA_WORKSPACE_MODEL — the Gmail/Calendar agent
    dashboard_model: str = ""  # NORA_DASHBOARD_MODEL — gen-UI dashboard / a2ui author / approval-card layout
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
    # First-party: ON by default (`langchain-mcp-adapters` is a base dependency now). Acting on the
    # operator's Google account still needs a running Workspace MCP server + the per-run OAuth token;
    # without a token the capability degrades to a friendly "connect" reply (never a crash). Turn it
    # OFF with NORA_WORKSPACE_ENABLED=false (the offline test suite pins it off — see tests/conftest.py).
    # Secrets (Google OAuth client id/secret, NEXTAUTH_SECRET) are NOT Settings fields — they're read
    # from the environment by the web layer + the Aegra auth handler, like every other provider key.
    workspace_enabled: bool = True  # master flag (NORA_WORKSPACE_ENABLED)
    # Human-in-the-loop gate for the workspace agent's *write* actions (send email, create event).
    # The single toggle that selects ONE mechanism so the two never double-gate the same tool:
    #   - "middleware": LangChain's prebuilt `HumanInTheLoopMiddleware` on a `create_agent` workspace
    #                   agent — the first-class framework HITL, and the DEFAULT. The middleware's
    #                   `interrupt_on` policy pauses each write tool call before it runs.
    #   - "primitive":  the hand-written loop's own batched `interrupt()` gate, kept as the
    #                   "show the mechanism" contrast (mirrors marketing's explicit interrupt). Same
    #                   `{"decisions": [...]}` resume protocol as middleware.
    #   - "off":        no gate — writes run straight through (the original, pre-HITL behaviour).
    # Default "middleware" → the framework gate is ON whenever the capability is enabled (the offline
    # suite pins workspace OFF, so this default never perturbs it; HITL tests set the mode explicitly).
    workspace_hitl: Literal["off", "primitive", "middleware"] = "middleware"  # NORA_WORKSPACE_HITL
    # The MCP server's streamable-http endpoint — note the `/mcp` path (the bare host returns 405).
    workspace_mcp_url: str = "http://localhost:8001/mcp"
    # Informational echo of the scopes the demo grants; the real enforcement is the MCP server's
    # `--permissions` flag (and the OAuth consent the operator approves).
    workspace_permissions: str = "gmail:send docs:full sheets:full tasks:full calendar:full drive:readonly"

    # --- Analytics tool guards ---
    max_sql_rows: int = 200  # LIMIT cap injected into run_sql
    sql_timeout_s: float = 5.0  # statement timeout

    # --- Marketing workflow knobs ---
    marketing_max_revisions: int = 2  # evaluator-optimizer loop bound
    marketing_num_concepts: int = 3  # parallel ideation count
    # Default Instagram-post size + caption verbosity. The operator adjusts both at the copy-review
    # gate (a stepper 1-8 + concise/standard/detailed) and regenerates; these are just the seeds.
    marketing_num_images: int = 4  # images per post (== on-screen-text lines); operator-adjustable
    marketing_verbosity: str = "standard"  # caption verbosity: concise | standard | detailed
    # Human-review gate on the generated stills, BEFORE the Instagram post is finalized (openrouter
    # renderer only — the placeholder has no stills to review, so the gate auto-passes). Turn off to
    # finalize the post straight from the stills with no pause.
    stills_review_enabled: bool = True  # NORA_STILLS_REVIEW_ENABLED
    stills_max_revisions: int = 3  # safety bound on the regenerate-stills loop

    # --- Rendering adapter ---
    # First-party: the real OpenRouter renderer by default. It needs an OPENROUTER_API_KEY to actually
    # render — without one, a marketing turn's render step fails loudly and is recorded as an error
    # (the brief still ships; construction is lazy, so non-rendering turns don't need the key). Set
    # NORA_RENDERER=placeholder for no external calls / no spend (the offline suite pins this — see
    # tests/conftest.py). Every model/knob below is overridable.
    renderer: Literal["placeholder", "openrouter"] = "openrouter"
    # Read from the UNPREFIXED OPENROUTER_API_KEY (what the comment/error name and users expect),
    # with NORA_OPENROUTER_API_KEY as a fallback. A plain field would only load NORA_OPENROUTER_API_KEY
    # (the env_prefix), so the documented OPENROUTER_API_KEY silently did nothing.
    openrouter_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENROUTER_API_KEY", "NORA_OPENROUTER_API_KEY"),
    )  # only used by the openrouter renderer
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # OpenRouter `provider/model` id for image generation (NOT an init_chat_model string). The
    # default is a Google model because it serves under OpenRouter's DEFAULT data policy — Black
    # Forest Labs' flux.* only routes through providers that need a relaxed policy
    # (https://openrouter.ai/settings/privacy), so it 404s ("No endpoints matching your guardrail
    # restrictions") out of the box. Cheaper models (e.g. flux.2-flex) work once that policy is
    # relaxed; override via NORA_OPENROUTER_IMAGE_MODEL.
    openrouter_image_model: str = "google/gemini-3.1-flash-image"
    # Per-shot render knobs. Instagram posts are vertical; keep resolution small to bound spend.
    render_aspect_ratio: str = "9:16"  # instagram post
    render_resolution: str = "720p"
    render_max_shots: int = 8  # HARD safety cap on rendered stills; the per-post count is marketing_num_images
    # Where generated images are written (served by the ops-api at /media).
    media_dir: Path = _DEFAULT_MEDIA_DIR

    def model_for(self, node: Literal["analytics", "marketing", "workspace", "dashboard"]) -> str:
        """The `provider:model` string for one LLM node, falling back to the base `model` when that
        node's override is empty. Lets each capability run its own model (see the per-node override
        fields above). The supervisor is the deliberate exception — it uses `router_model`, built in
        orchestrator.py:_build_supervisor_model — so it's intentionally not routed through here."""
        return {
            "analytics": self.analytics_model,
            "marketing": self.marketing_model,
            "workspace": self.workspace_model,
            "dashboard": self.dashboard_model,
        }[node] or self.model

    def workspace_scope_summary(self) -> str:
        """A human-readable summary of the Google Workspace scopes actually granted (parsed from
        `workspace_permissions`). Every prompt that tells the router / workspace agent what the
        capability can do is built from THIS, so the descriptions stay in lockstep with the real
        grant instead of drifting (the "Gmail + Calendar only" staleness bug). Unknown scopes still
        surface with a sane generic label, so adding a scope automatically widens the descriptions."""
        parts: list[str] = []
        for token in self.workspace_permissions.split():
            area, _, level = token.partition(":")
            if not area:
                continue
            label = _WORKSPACE_SCOPE_LABELS.get((area, level))
            if label is None:
                label = f"Google {area.replace('_', ' ').title()}" + (f" ({level})" if level else "")
            parts.append(label)
        if not parts:
            return "the operator's Google account"
        if len(parts) == 1:
            return parts[0]
        return ", ".join(parts[:-1]) + ", and " + parts[-1]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return Settings()
