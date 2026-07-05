// Plane 2 — Google Workspace authorization (server-side only; imported solely by app/api/google/*).
// The separate, incremental grant: the operator approves the heavy Gmail/Calendar scopes here, NOT
// at login. Tokens live in an encrypted, httpOnly, session-scoped cookie (no DB) — minimal on
// purpose, since Testing-mode refresh tokens expire in 7 days anyway. The cookie is encrypted with a
// key derived from AUTH_SECRET so its contents never leave the server in the clear.

import { createHash } from "crypto";
import { EncryptJWT, jwtDecrypt } from "jose";

import { AUTH_SECRET } from "@/lib/auth-secret";

// The heavy scopes the incremental grant requests. MUST be a subset of what's configured on the
// Google OAuth consent screen (Data Access), or the grant flow fails / shows un-consented scopes.
export const GOOGLE_WORKSPACE_SCOPES = [
  "https://www.googleapis.com/auth/gmail.readonly", // read inbox (summaries, "latest emails")
  "https://www.googleapis.com/auth/gmail.compose", // manage drafts + send
  "https://www.googleapis.com/auth/documents", // edit Google Docs
  "https://www.googleapis.com/auth/spreadsheets", // edit Google Sheets
  "https://www.googleapis.com/auth/tasks", // manage Tasks
  "https://www.googleapis.com/auth/calendar", // read + create/modify calendar events
  "https://www.googleapis.com/auth/drive.file", // create/open only the files the app touches
  "https://www.googleapis.com/auth/drive.readonly", // find/read existing Drive files
];

export const GW_COOKIE = "gw_tokens";

// One-time CSRF token for the incremental grant: connect plants it (cookie + ?state=), callback
// requires the echoed value to match and then consumes it. Without it, a forged GET to the callback
// could bind an attacker's Google tokens into the victim's session.
export const GW_STATE_COOKIE = "gw_oauth_state";

export interface GoogleTokens {
  access_token: string;
  refresh_token?: string;
  expires_at: number; // epoch ms
}

function cookieKey(): Uint8Array {
  // A256GCM needs a 32-byte key; SHA-256 of the shared signing secret gives exactly that,
  // deterministically. (The secret's source/fallback policy lives in lib/auth-secret.)
  return new Uint8Array(createHash("sha256").update(AUTH_SECRET).digest());
}

export function redirectUri(): string {
  const base = process.env.NEXTAUTH_URL ?? "http://localhost:3000";
  return `${base.replace(/\/$/, "")}/api/google/callback`;
}

export async function encryptTokens(tokens: GoogleTokens): Promise<string> {
  return await new EncryptJWT({ ...tokens })
    .setProtectedHeader({ alg: "dir", enc: "A256GCM" })
    .setIssuedAt()
    .encrypt(cookieKey());
}

async function decryptTokens(value: string): Promise<GoogleTokens | null> {
  try {
    const { payload } = await jwtDecrypt(value, cookieKey());
    if (typeof payload.access_token !== "string") return null;
    return {
      access_token: payload.access_token,
      refresh_token: typeof payload.refresh_token === "string" ? payload.refresh_token : undefined,
      expires_at: typeof payload.expires_at === "number" ? payload.expires_at : 0,
    };
  } catch {
    return null;
  }
}

// Exchange a fresh authorization code for tokens (the first leg of the incremental grant). Mirrors
// refreshAccessToken below — both POST to Google's token endpoint — so the two live together here
// rather than inline in the route handler. Returns null on any failure; the caller redirects to an
// error page.
export async function exchangeCodeForTokens(code: string): Promise<GoogleTokens | null> {
  const res = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      code,
      client_id: process.env.GOOGLE_CLIENT_ID ?? "",
      client_secret: process.env.GOOGLE_CLIENT_SECRET ?? "",
      redirect_uri: redirectUri(),
      grant_type: "authorization_code",
    }),
    cache: "no-store",
  });
  if (!res.ok) return null;
  const tok = await res.json();
  if (!tok.access_token) return null;
  return {
    access_token: tok.access_token,
    refresh_token: tok.refresh_token,
    expires_at: Date.now() + (tok.expires_in ?? 3600) * 1000,
  };
}

async function refreshAccessToken(refreshToken: string): Promise<GoogleTokens | null> {
  const res = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: process.env.GOOGLE_CLIENT_ID ?? "",
      client_secret: process.env.GOOGLE_CLIENT_SECRET ?? "",
      grant_type: "refresh_token",
      refresh_token: refreshToken,
    }),
    cache: "no-store",
  });
  if (!res.ok) return null;
  const tok = await res.json();
  if (!tok.access_token) return null;
  return {
    access_token: tok.access_token,
    refresh_token: refreshToken, // Google doesn't re-issue the refresh token on refresh
    expires_at: Date.now() + (tok.expires_in ?? 3600) * 1000,
  };
}

// Resolve the operator's CURRENT access token from the raw encrypted cookie value, refreshing if it's
// stale. Single source of truth shared by BOTH /api/google/token (returns it) and /api/google/status
// (reports connected = resolvable) so the two can never disagree. Returns:
//   - { access_token, rotatedCookie } — valid token; rotatedCookie is non-null only when a refresh
//     happened (the caller must re-set the cookie so the refreshed token persists).
//   - null — the cookie is unusable (decrypt failed / expired with no refresh token / refresh failed).
//     The caller should treat this as DISCONNECTED and clear the stale cookie, so a dead grant can't
//     keep reporting "connected" while every token fetch returns null.
export async function resolveAccessToken(
  raw: string,
): Promise<{ access_token: string; rotatedCookie: string | null } | null> {
  const tokens = await decryptTokens(raw);
  if (!tokens) return null;
  if (Date.now() <= tokens.expires_at - 60_000) {
    return { access_token: tokens.access_token, rotatedCookie: null };
  }
  if (!tokens.refresh_token) return null;
  const refreshed = await refreshAccessToken(tokens.refresh_token);
  if (!refreshed) return null;
  return { access_token: refreshed.access_token, rotatedCookie: await encryptTokens(refreshed) };
}

// Standard httpOnly cookie options for the encrypted token bundle (7 days ~ the Testing-mode cap).
export const GW_COOKIE_OPTIONS = {
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  path: "/",
  maxAge: 60 * 60 * 24 * 7,
};
