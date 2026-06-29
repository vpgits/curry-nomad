"""Structured logging + tracing setup.

The lesson here: replace `print()` with structured events and a trace. Every meaningful
event is logged through `structlog` with consistent keys (see EVENTS below), and a
correlation id (`run_id` / `thread_id`) is bound via context vars so it rides along on
every log line within a run.

Two tracers, both *env-gated and optional* — the app runs fine with neither:

- **LangSmith** needs *no code*: it turns on automatically when `LANGSMITH_TRACING=true`
  (plus `LANGSMITH_API_KEY`) is set in the environment, and a trace then shows the analytics
  agent loop and the marketing workflow supersteps for free.
- **Langfuse** (self-hostable, see `docker-compose.langfuse.yml`) is wired explicitly via a
  LangChain `CallbackHandler` — `get_langfuse_handler()` below. The CLI attaches it to the run
  config (`config["callbacks"]`), and because the orchestrator passes that same `config` into
  the analytics agent and the marketing workflow, one attach point traces *everything*. Model
  name, token usage, and observation types come for free from the LangChain integration. Like
  the provider keys, Langfuse credentials live only in the environment (never in `Settings`),
  and the `langfuse` dependency is an optional extra (`uv sync --extra langfuse`), imported
  lazily so the base install — and the offline tests — never need it.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog

# Canonical event names emitted across the app. Keeping them in one place keeps the logs
# greppable and the teaching story consistent. (Documented keys in parentheses.)
EVENTS = {
    "route.decided": "capability, reason",
    "sql.run": "query, rows, ms",
    "sql.error": "query, error",
    "sql.repair": "query",
    "hitl.raised": "question",
    "hitl.resumed": "decision",
    "marketing.revision": "iteration, verdict",
    "render.placeholder": "shots",
    "eval.scored": "id, metric, score",
    # Operations (inventory + orders + delivery routing). Every mutation logs one event;
    # rejections (the agentic "limits" — oversell, write-off below zero) get their own keys.
    "ops.receive": "product_id, qty, on_hand",
    "ops.adjust": "product_id, qty_delta, on_hand, reason",
    "ops.write_off_rejected": "product_id, qty_delta, on_hand, reserved",
    "ops.order_created": "order_id, customer_id, total_lkr, lines",
    "ops.oversell_rejected": "product_id, requested, available",
    "ops.route_planned": "route_id, stops, total_km, naive_km",
    "ops.dispatched": "route_id, deliveries",
    "ops.seed.built": "products, orders, deliveries",
}

_configured = False


def setup_logging(level: str = "INFO", *, json_logs: bool = True) -> None:
    """Configure structlog once. JSON by default; pretty console output when ``json_logs``
    is False (handy for local demos)."""
    global _configured

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,  # pulls in bound run_id/thread_id
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    _configured = True


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Return a bound logger, configuring structlog with sane defaults on first use."""
    if not _configured:
        setup_logging()
    return structlog.get_logger(name)


def bind_context(**kwargs: Any) -> None:
    """Bind correlation ids (e.g. ``run_id=``, ``thread_id=``) for the current context."""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear any bound context vars (call at the end of a run/turn)."""
    structlog.contextvars.clear_contextvars()


# --- Langfuse tracing (optional) -------------------------------------------------------------
# Gated on `LANGFUSE_PUBLIC_KEY` being present, so the whole feature is a no-op until someone
# opts in by setting the env vars. The import is lazy (inside the function) so the base install
# without the `langfuse` extra still imports this module and the offline tests pass.

_langfuse_warned = False


def get_langfuse_handler():
    """Return a configured Langfuse LangChain ``CallbackHandler``, or ``None``.

    Returns ``None`` (a graceful no-op) when Langfuse isn't configured — either the env isn't
    set (`LANGFUSE_PUBLIC_KEY` missing) or the optional `langfuse` extra isn't installed. Attach
    the returned handler to a run config as ``config["callbacks"] = [handler]`` and it traces the
    whole orchestrator (the analytics agent + the marketing workflow) in one shot, since the
    orchestrator passes its `config` straight through into both subgraphs.

    Credentials are read straight from the environment (never `Settings`), mirroring how provider
    keys and `LANGSMITH_*` are handled: ``LANGFUSE_PUBLIC_KEY``, ``LANGFUSE_SECRET_KEY``,
    ``LANGFUSE_HOST``. In SDK v3 the ``CallbackHandler`` takes *no* credential args — the Langfuse
    client it wraps picks them up from the environment.
    """
    global _langfuse_warned

    if not os.environ.get("LANGFUSE_PUBLIC_KEY"):
        return None  # not configured — stay a no-op

    try:
        from langfuse.langchain import CallbackHandler  # lazy: needs the optional extra
    except ImportError:
        if not _langfuse_warned:  # warn once, then keep quiet
            get_logger(__name__).warning(
                "langfuse.unavailable",
                hint="LANGFUSE_PUBLIC_KEY is set but the `langfuse` package isn't installed; "
                "run `uv sync --extra langfuse` to enable tracing",
            )
            _langfuse_warned = True
        return None

    return CallbackHandler()


def flush_langfuse() -> None:
    """Flush any buffered Langfuse events. A no-op unless Langfuse is configured + installed.

    The skill flags "no flush in scripts" as a top mistake: the SDK batches events in the
    background, so a short-lived CLI process can exit before they're sent. Call this before the
    process returns. (`get_client()` returns the same singleton the CallbackHandler uses.)
    """
    if not os.environ.get("LANGFUSE_PUBLIC_KEY"):
        return
    try:
        from langfuse import get_client  # lazy: needs the optional extra
    except ImportError:
        return
    get_client().flush()


def score_trace(
    trace_id: str | None,
    name: str,
    value: float | int | str,
    *,
    data_type: str = "NUMERIC",
    comment: str | None = None,
) -> None:
    """Attach one Langfuse *score* to a trace by id. A no-op unless Langfuse is configured.

    This is the skill's "capture as scores" best practice: an eval result (a deterministic
    correctness check, or an LLM-judge axis) is recorded on the trace it scores, so the Langfuse
    UI can filter/aggregate by quality. The eval runner reads ``handler.last_trace_id`` after each
    item's run and pushes the per-item metrics through here.

    Mirrors `get_langfuse_handler` / `flush_langfuse`: gated on ``LANGFUSE_PUBLIC_KEY`` and the
    optional `langfuse` extra (lazy import), so the base install and the offline tests never need
    it. Per the skill, ``data_type`` is set explicitly — a boolean ``1`` would otherwise be inferred
    as NUMERIC. Score creation is *best-effort*: a tracing hiccup must never break an eval run, so a
    failure is logged and swallowed (the same posture as the gen-UI pushes).
    """
    if not trace_id or not os.environ.get("LANGFUSE_PUBLIC_KEY"):
        return  # not configured, or no trace to attach to — stay a no-op
    try:
        from langfuse import get_client  # lazy: needs the optional extra
    except ImportError:
        return
    try:
        get_client().create_score(
            trace_id=trace_id, name=name, value=value, data_type=data_type, comment=comment
        )
    except Exception:  # noqa: BLE001 — tracing is best-effort; never fail the run over a score
        get_logger(__name__).warning("langfuse.score_failed", score=name, trace_id=trace_id)
