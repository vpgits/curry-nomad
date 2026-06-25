// Plane 2 — Google Workspace authorization (server-side only; imported solely by app/api/google/*).
// The separate, incremental grant: the operator approves the heavy Gmail/Calendar scopes here, NOT
// at login. Tokens live in an encrypted, httpOnly, session-scoped cookie (no DB) — minimal on
// purpose, since Testing-mode refresh tokens expire in 7 days anyway. The cookie is encrypted with a
// key derived from AUTH_SECRET so its contents never leave the server in the clear.

import { createHash } from "crypto";
import { EncryptJWT, jwtDecrypt } from "jose";

// The heavy scopes the incremental grant requests. MUST be a subset of what's configured on the
// Google OAuth consent screen (Data Access), or the grant flow fails / shows un-consented scopes.
export const GOOGLE_WORKSPACE_SCOPES = [
  "https://www.googleapis.com/auth/gmail.readonly", // read inbox (summaries, "latest emails")
  "https://www.googleapis.com/auth/gmail.compose", // manage drafts + send
  "https://www.googleapis.com/auth/documents", // edit Google Docs
  "https://www.googleapis.com/auth/spreadsheets", // edit Google Sheets
  "https://www.googleapis.com/auth/tasks", // manage Tasks
  "https://www.googleapis.com/auth/drive.file", // create/open only the files the app touches
  "https://www.googleapis.com/auth/drive.readonly", // find/read existing Drive files
];

export const GW_COOKIE = "gw_tokens";

export interface GoogleTokens {
  access_token: string;
  refresh_token?: string;
  expires_at: number; // epoch ms
}

function cookieKey(): Uint8Array {
  const secret =
    process.env.AUTH_SECRET ??
    process.env.NEXTAUTH_SECRET ??
    "nora-dev-insecure-secret-please-override-0123456789";
  // A256GCM needs a 32-byte key; SHA-256 of the secret gives exactly that, deterministically.
  return new Uint8Array(createHash("sha256").update(secret).digest());
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

export async function decryptTokens(value: string): Promise<GoogleTokens | null> {
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

export async function refreshAccessToken(refreshToken: string): Promise<GoogleTokens | null> {
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

// Standard httpOnly cookie options for the encrypted token bundle (7 days ~ the Testing-mode cap).
export const GW_COOKIE_OPTIONS = {
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  path: "/",
  maxAge: 60 * 60 * 24 * 7,
};
