"""Aegra custom-auth handler (Plane 1 — app identity).

Verifies the short HS256 JWT the web app (NextAuth) mints for the logged-in operator and returns
their identity, so Aegra scopes threads per operator. Referenced from `aegra.json` (`auth.path`) and
activated by `AUTH_TYPE=custom` (default `noop` keeps local dev keyless). The signing secret
(`NEXTAUTH_SECRET`) is read straight from the environment — never a `Settings` field, like every
other secret in this project (provider keys, LANGFUSE_*, …).

Scope: this is ONLY authentication (who is logged in). The operator's Google Workspace
*authorization* — the access token the `workspace` capability calls Google with — is a separate
concern carried per-run in the request config (see `orchestrator.workspace`). We also decode an
optional `google_access_token` claim here so a future "variant B" (token in the auth JWT instead of
run config, so it never lands in a checkpoint) is a one-line change.

`pyjwt` lives in the optional `workspace` extra and is imported lazily, so merely importing this
module (e.g. when Aegra boots under `AUTH_TYPE=noop`) needs nothing beyond `langgraph_sdk`.
"""

from __future__ import annotations

import os

from langgraph_sdk import Auth

auth = Auth()

_ALGORITHMS = ["HS256"]


def _bearer(headers) -> str | None:
    """Extract the bearer token from request headers (case-insensitive; str or bytes values)."""
    if not hasattr(headers, "get"):
        return None
    for key in ("authorization", b"authorization", "Authorization"):
        value = headers.get(key)
        if value:
            if isinstance(value, bytes):
                value = value.decode()
            return value.removeprefix("Bearer ").removeprefix("bearer ").strip()
    return None


def verify_session_token(token: str, secret: str) -> dict:
    """Decode + verify the NextAuth session JWT and return the Aegra user dict.

    Pure (no env/headers) so it's unit-testable. Raises on an invalid/expired signature or a token
    with no subject — the caller turns that into an auth rejection.
    """
    import jwt  # pyjwt; optional `workspace` extra

    payload = jwt.decode(token, secret, algorithms=_ALGORITHMS)
    identity = payload.get("sub") or payload.get("email")
    if not identity:
        raise ValueError("session token has no subject/email claim")
    return {
        "identity": identity,
        "display_name": payload.get("name", ""),
        "is_authenticated": True,
        # Carried for a future variant-B (token in the JWT, not run config); unused by Plan A today.
        "google_access_token": payload.get("google_access_token"),
    }


@auth.authenticate
async def authenticate(headers) -> dict:
    # Master switch. The handler is declared in aegra.json, but we only ENFORCE when AUTH_TYPE=custom.
    # Otherwise (the default `noop`) every request is an anonymous user — so registering this handler
    # never breaks the keyless default stack (analytics/marketing/routing). Belt-and-suspenders: it
    # makes the keyless default hold whether Aegra gates enforcement on AUTH_TYPE or on the mere
    # presence of the `auth` key.
    if os.environ.get("AUTH_TYPE", "noop").lower() != "custom":
        return {"identity": "anonymous", "display_name": "", "is_authenticated": True}
    secret = os.environ.get("NEXTAUTH_SECRET")
    if not secret:
        # Misconfiguration: AUTH_TYPE=custom but no signing secret. Fail loud (500) rather than admit
        # everyone — silently accepting all callers is worse than no auth at all.
        raise Auth.exceptions.HTTPException(
            status_code=500, detail="NEXTAUTH_SECRET is not configured"
        )
    token = _bearer(headers)
    if not token:
        # Raise the SDK's typed exception so Aegra returns a clean 401. A bare Exception is caught as
        # an internal error and surfaces to the client as the opaque "Authentication system error".
        raise Auth.exceptions.HTTPException(status_code=401, detail="Missing bearer token")
    try:
        return verify_session_token(token, secret)
    except Auth.exceptions.HTTPException:
        raise
    except Exception as exc:  # invalid/expired signature, or no subject → reject
        raise Auth.exceptions.HTTPException(
            status_code=401, detail=f"Invalid session token: {exc}"
        ) from exc
