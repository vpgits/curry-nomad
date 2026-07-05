"""Dynamic per-run context, folded into agent prompts AFTER the static (cacheable) prompt prefix.

The system prompts are a stable, cache-friendly prefix; anything that changes per run — the current
date/time, the operator's timezone — must NOT be baked into that prefix. Doing so would bust the
prompt cache (OpenAI caches the longest stable prefix automatically) and, worse, the baked-in "today"
would go stale. So the web client stamps `client_now` (UTC ISO 8601) + `client_timezone` (IANA name)
onto `config.configurable` at submit time (see apps/web/lib/run-config.ts), and a node appends this
formatted block to the END of its system prompt.

Why the CLIENT is the source: the server's clock/timezone is not the operator's. A Colombo operator
asking to "create a calendar event today at 5pm" needs it in Asia/Colombo, not the server's UTC — so
the browser is authoritative for both "now" and "where". Empty string when nothing was sent (e.g. the
CLI path), so a prompt with no runtime context is byte-for-byte unchanged.

Deliberately NOT applied to the analytics agent: it reasons over the bundled dataset relative to the
fixed `settings.data_as_of`, so injecting the real wall-clock "now" there would break its determinism.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from nora.observability import get_logger

log = get_logger(__name__)


def runtime_context_block(config: dict | None) -> str:
    """Format the client-supplied `client_now` / `client_timezone` (from `config.configurable`) into a
    short prompt block. Returns "" when the client sent neither (so the prompt is unchanged)."""
    cfg = (config or {}).get("configurable", {}) if config else {}
    now_iso = cfg.get("client_now")
    tz_name = cfg.get("client_timezone")
    if not now_iso and not tz_name:
        return ""

    lines = ["Current context (live — the operator's clock right now, not the server's):"]
    local = _local_now(now_iso, tz_name)
    if local is not None:
        # e.g. "Sunday, 05 July 2026, 05:35 PM (UTC+0530)"
        lines.append(
            f"- Current date and time: {local.strftime('%A, %d %B %Y, %I:%M %p')} "
            f"(UTC{local.strftime('%z')})"
        )
    elif now_iso:  # couldn't localise (bad/absent tz) — give the raw UTC instant so it's not lost
        lines.append(f"- Current date and time (UTC): {now_iso}")
    if tz_name:
        lines.append(
            f"- Operator's timezone: {tz_name}. Interpret relative times like \"today 5pm\" or "
            "\"tomorrow morning\" in THIS timezone unless the operator names another — do not ask "
            "which timezone to use."
        )
    return "\n".join(lines)


def _local_now(now_iso: str | None, tz_name: str | None) -> datetime | None:
    """The operator's local `datetime` from a UTC ISO string + IANA tz name, or None if either is
    missing / unparseable (the caller then falls back to the raw ISO or omits the line)."""
    if not now_iso or not tz_name:
        return None
    try:
        # `new Date().toISOString()` emits a trailing "Z"; fromisoformat wants an explicit offset.
        dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo(tz_name))
    except Exception as exc:  # noqa: BLE001 — best-effort formatting; never break a turn on a bad value
        log.info("runtime_context.parse_failed", now=now_iso, tz=tz_name, error=str(exc))
        return None
