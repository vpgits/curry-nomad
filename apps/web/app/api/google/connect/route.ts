import { NextResponse, type NextRequest } from "next/server";

import { auth } from "@/auth";
import { GOOGLE_WORKSPACE_SCOPES, redirectUri } from "@/lib/google";

// Start the incremental Google Workspace grant: redirect the (already logged-in) operator to Google's
// consent screen for the heavy scopes only, with offline access so we get a refresh token.
export async function GET(req: NextRequest) {
  const session = await auth();
  if (!session) {
    return NextResponse.redirect(new URL("/api/auth/signin", req.nextUrl.origin));
  }
  const url = new URL("https://accounts.google.com/o/oauth2/v2/auth");
  url.searchParams.set("client_id", process.env.GOOGLE_CLIENT_ID ?? "");
  url.searchParams.set("redirect_uri", redirectUri());
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", GOOGLE_WORKSPACE_SCOPES.join(" "));
  url.searchParams.set("access_type", "offline");
  url.searchParams.set("prompt", "consent"); // force a refresh_token even on re-grant
  url.searchParams.set("include_granted_scopes", "true");
  return NextResponse.redirect(url);
}
