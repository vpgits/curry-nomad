"""Tests for the Aegra custom-auth handler (Plane 1 identity).

The bearer-extraction logic runs offline; the JWT-verification tests need `pyjwt` (the optional
`workspace` extra), so they `importorskip("jwt")` and are skipped in the base offline run — the same
gating style as the live-model tests.
"""

from __future__ import annotations

import pytest

from nora.auth import _bearer


def test_bearer_extraction_is_case_insensitive_and_handles_bytes():
    assert _bearer({"authorization": "Bearer abc"}) == "abc"
    assert _bearer({b"authorization": b"Bearer xyz"}) == "xyz"
    assert _bearer({"Authorization": "bearer Q"}) == "Q"
    assert _bearer({}) is None
    assert _bearer({"authorization": ""}) is None


def test_verify_session_token_roundtrip():
    jwt = pytest.importorskip("jwt")
    from nora.auth import verify_session_token

    token = jwt.encode(
        {"sub": "arun@example.com", "name": "Arun", "google_access_token": "ya29.tok"},
        "test-secret-at-least-32-bytes-long!!",
        algorithm="HS256",
    )
    user = verify_session_token(token, "test-secret-at-least-32-bytes-long!!")
    assert user["identity"] == "arun@example.com"
    assert user["display_name"] == "Arun"
    assert user["is_authenticated"] is True
    assert user["google_access_token"] == "ya29.tok"  # carried for variant-B readiness


def test_verify_session_token_rejects_bad_signature():
    jwt = pytest.importorskip("jwt")
    from nora.auth import verify_session_token

    token = jwt.encode({"sub": "arun"}, "right-secret-at-least-32-bytes-long!", algorithm="HS256")
    with pytest.raises(Exception):  # noqa: B017 — any verification failure must reject
        verify_session_token(token, "wrong-secret-at-least-32-bytes-long!")


def test_verify_session_token_requires_a_subject():
    jwt = pytest.importorskip("jwt")
    from nora.auth import verify_session_token

    token = jwt.encode({"name": "no subject"}, "test-secret-at-least-32-bytes-long!!", algorithm="HS256")
    with pytest.raises(ValueError):
        verify_session_token(token, "test-secret-at-least-32-bytes-long!!")
