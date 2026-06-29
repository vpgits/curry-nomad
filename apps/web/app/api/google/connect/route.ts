import { randomBytes } from "crypto";

import { NextResponse, type NextRequest } from "next/server";

import { auth } from "@/auth";
import { GOOGLE_WORKSPACE_SCOPES, GW_STATE_COOKIE, redirectUri } from "@/lib/google";

// Start the incremental Google Workspace grant: redirect the (already logged-in) operator to Google's
// consent screen for the heavy scopes only, with offline access so we get a refresh token.
export async function GET(req: NextRequest) {
  const session = await auth();
  if (!session) {
    return NextResponse.redirect(new URL("/api/auth/signin", req.nextUrl.origin));
  }

  // One-time CSRF token: Google echoes `state` back to the callback, which requires it to match this
  // cookie. Binds the grant to the browser that started it, so a forged callback can't plant tokens.
  const state = randomBytes(32).toString("hex");

  const url = new URL("https://accounts.google.com/o/oauth2/v2/auth");
  url.searchParams.set("client_id", process.env.GOOGLE_CLIENT_ID ?? "");
  url.searchParams.set("redirect_uri", redirectUri());
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", GOOGLE_WORKSPACE_SCOPES.join(" "));
  url.searchParams.set("access_type", "offline");
  url.searchParams.set("prompt", "consent"); // force a refresh_token even on re-grant
  url.searchParams.set("include_granted_scopes", "true");
  url.searchParams.set("state", state);

  const res = NextResponse.redirect(url);
  res.cookies.set(GW_STATE_COOKIE, state, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax", // survives Google's top-level GET redirect back to the callback
    path: "/api/google",
    maxAge: 600, // 10 minutes to complete consent
  });
  return res;
}
