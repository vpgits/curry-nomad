"""Structured logging + tracing setup.

The lesson here: replace `print()` with structured events and a trace. Every meaningful
event is logged through `structlog` with consistent keys (see EVENTS below), and a
correlation id (`run_id` / `thread_id`) is bound via context vars so it rides along on
every log line within a run.

LangSmith tracing needs *no code*: it turns on automatically when `LANGSMITH_TRACING=true`
(plus `LANGSMITH_API_KEY`) is set in the environment, and a trace then shows the analytics
agent loop and the marketing workflow supersteps for free.
"""

from __future__ import annotations

import logging
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
