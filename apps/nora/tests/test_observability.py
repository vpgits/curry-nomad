"""Tests for the optional Langfuse tracing factory.

These stay fully offline and key-free: `get_langfuse_handler()` is gated on the
`LANGFUSE_PUBLIC_KEY` env var, so with no env set it must return `None` (a graceful no-op).
Constructing a handler (when the extra is installed) is allowed — but it must NOT open a
network connection, so we never flush or send anything here.
"""

from __future__ import annotations

import pytest

from nora.observability import flush_langfuse, get_langfuse_handler


def test_handler_is_none_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No `LANGFUSE_PUBLIC_KEY` -> tracing is a no-op (returns None)."""
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    assert get_langfuse_handler() is None


def test_flush_is_noop_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flushing without Langfuse configured must not raise (and must not connect)."""
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    flush_langfuse()  # should simply return


def test_handler_built_when_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """With env set and the `langfuse` extra installed, a handler is returned.

    Skipped when the optional extra isn't installed. Constructing the handler is offline; we
    never flush/connect, so no network call is made.
    """
    pytest.importorskip("langfuse")

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_HOST", "http://localhost:3001")

    handler = get_langfuse_handler()
    assert handler is not None
