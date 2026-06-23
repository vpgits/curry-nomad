import { NextResponse, type NextRequest } from "next/server";

import { auth } from "@/auth";
import {
  GW_COOKIE,
  GW_COOKIE_OPTIONS,
  decryptTokens,
  encryptTokens,
  refreshAccessToken,
} from "@/lib/google";

// Return the operator's CURRENT Google access token (refreshing it server-side if stale), so the
// chat client can hand it to the workspace agent per run. The refresh token never leaves the server.
export async function GET(req: NextRequest) {
  const session = await auth();
  if (!session) return NextResponse.json({ access_token: null }, { status: 401 });

  const raw = req.cookies.get(GW_COOKIE)?.value;
  if (!raw) return NextResponse.json({ access_token: null });

  let tokens = await decryptTokens(raw);
  if (!tokens) return NextResponse.json({ access_token: null });

  let rotatedCookie: string | null = null;
  if (Date.now() > tokens.expires_at - 60_000) {
    // Expired (or about to) — refresh, or give up if there's no refresh token (re-connect needed).
    if (!tokens.refresh_token) return NextResponse.json({ access_token: null });
    const refreshed = await refreshAccessToken(tokens.refresh_token);
    if (!refreshed) return NextResponse.json({ access_token: null });
    tokens = refreshed;
    rotatedCookie = await encryptTokens(tokens);
  }

  const res = NextResponse.json({ access_token: tokens.access_token });
  if (rotatedCookie) res.cookies.set(GW_COOKIE, rotatedCookie, GW_COOKIE_OPTIONS);
  return res;
}
