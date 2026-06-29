import { randomBytes } from "crypto";

// The HS256 signing secret shared by the NextAuth session (auth.ts, which the backend's auth.py
// verifies) and the Workspace token cookie's encryption key (lib/google.ts). It is resolved ONCE,
// here, so both planes agree on its source and there is a single place to reason about it.
//
// In production it MUST come from the environment (and equal the backend's NEXTAUTH_SECRET) — there
// is deliberately NO committed fallback, because a hardcoded literal would ship a known secret and
// silently "fail open" the moment the env var was forgotten. In dev / auth-off mode (AUTH_TYPE=noop,
// where the backend never verifies the token) we mint an EPHEMERAL per-process secret so the default
// stack still boots without anyone setting an env var. Ephemeral ≠ hardcoded: nothing secret is
// committed and the value is unpredictable, so a leaked repo can't be used to forge a session.
function resolveAuthSecret(): string {
  const fromEnv = process.env.AUTH_SECRET ?? process.env.NEXTAUTH_SECRET;
  if (fromEnv) return fromEnv;
  if (process.env.NODE_ENV === "production") {
    throw new Error(
      "AUTH_SECRET (or NEXTAUTH_SECRET) must be set in production — it signs the operator session " +
        "token the backend verifies and derives the Workspace cookie key.",
    );
  }
  // Dev/auth-off only: a fresh secret per server process. Restarting dev invalidates existing
  // sessions/cookies (operators re-login), which is fine when nothing is being verified.
  return randomBytes(32).toString("hex");
}

export const AUTH_SECRET: string = resolveAuthSecret();
