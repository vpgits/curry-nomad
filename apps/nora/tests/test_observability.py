"""Tests for the optional Langfuse tracing factory.

These stay fully offline and key-free: `get_langfuse_handler()` is gated on the
`LANGFUSE_PUBLIC_KEY` env var, so with no env set it must return `None` (a graceful no-op).
Constructing a handler (when the extra is installed) is allowed — but it must NOT open a
network connection, so we never flush or send anything here.
"""

from __future__ import annotations

import pytest

from nora.observability import flush_langfuse, get_langfuse_handler, score_trace


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


def test_score_trace_is_noop_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No `LANGFUSE_PUBLIC_KEY` -> scoring is a no-op (must not raise, must not connect)."""
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    score_trace("trace-123", "eval-correct", 1, data_type="BOOLEAN")  # should simply return


def test_score_trace_is_noop_without_trace_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing trace id (the handler produced none) is a no-op, even with env set."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    score_trace(None, "eval-correct", 1, data_type="BOOLEAN")  # should simply return


def test_score_trace_calls_create_score(monkeypatch: pytest.MonkeyPatch) -> None:
    """With env set, score_trace forwards to the SDK's create_score with explicit data_type.

    Offline: the `langfuse` client is faked, so no network call is made. This pins the helper's
    call wiring (the only part of the score path testable without a live server).
    """
    pytest.importorskip("langfuse")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")

    calls: list[dict] = []

    class _FakeClient:
        def create_score(self, **kwargs):  # noqa: ANN003
            calls.append(kwargs)

    import langfuse

    monkeypatch.setattr(langfuse, "get_client", lambda: _FakeClient())
    score_trace("trace-123", "eval-correct", 1, data_type="BOOLEAN", comment="ok")

    assert len(calls) == 1
    assert calls[0] == {
        "trace_id": "trace-123",
        "name": "eval-correct",
        "value": 1,
        "data_type": "BOOLEAN",
        "comment": "ok",
    }


def test_score_trace_swallows_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failure in the SDK must never propagate — tracing is best-effort."""
    pytest.importorskip("langfuse")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")

    class _BoomClient:
        def create_score(self, **kwargs):  # noqa: ANN003
            raise RuntimeError("server down")

    import langfuse

    monkeypatch.setattr(langfuse, "get_client", lambda: _BoomClient())
    score_trace("trace-123", "eval-correct", 1, data_type="BOOLEAN")  # must not raise
