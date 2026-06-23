import { NextResponse, type NextRequest } from "next/server";

import { auth } from "@/auth";
import { GW_COOKIE, GW_COOKIE_OPTIONS, encryptTokens, redirectUri } from "@/lib/google";

// Finish the incremental grant: exchange the code for tokens and stash them in an encrypted,
// httpOnly, session-scoped cookie. Then bounce back to /ask. Best-effort — any failure just lands on
// /ask?gw=error and the operator can retry.
export async function GET(req: NextRequest) {
  const origin = req.nextUrl.origin;
  const session = await auth();
  if (!session) return NextResponse.redirect(new URL("/", origin));

  const code = req.nextUrl.searchParams.get("code");
  if (!code) return NextResponse.redirect(new URL("/ask?gw=error", origin));

  const tokenRes = await fetch("https://oauth2.googleapis.com/token", {
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
  if (!tokenRes.ok) return NextResponse.redirect(new URL("/ask?gw=error", origin));

  const tok = await tokenRes.json();
  if (!tok.access_token) return NextResponse.redirect(new URL("/ask?gw=error", origin));

  const cookieValue = await encryptTokens({
    access_token: tok.access_token,
    refresh_token: tok.refresh_token,
    expires_at: Date.now() + (tok.expires_in ?? 3600) * 1000,
  });
  const out = NextResponse.redirect(new URL("/ask?gw=connected", origin));
  out.cookies.set(GW_COOKIE, cookieValue, GW_COOKIE_OPTIONS);
  return out;
}
