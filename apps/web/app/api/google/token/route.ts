import { NextResponse, type NextRequest } from "next/server";

import { auth } from "@/auth";
import { GW_COOKIE, GW_COOKIE_OPTIONS, resolveAccessToken } from "@/lib/google";

// Return the operator's CURRENT Google access token (refreshing it server-side if stale), so the
// chat client can hand it to the workspace agent per run. The refresh token never leaves the server.
export async function GET(req: NextRequest) {
  const session = await auth();
  if (!session) return NextResponse.json({ access_token: null }, { status: 401 });

  const raw = req.cookies.get(GW_COOKIE)?.value;
  if (!raw) return NextResponse.json({ access_token: null });

  const resolved = await resolveAccessToken(raw);
  if (!resolved) {
    // Cookie present but unusable (decrypt/expiry/refresh failed) → clear it so /status stops
    // reporting "connected" for a grant that can no longer mint a token.
    const res = NextResponse.json({ access_token: null });
    res.cookies.delete(GW_COOKIE);
    return res;
  }

  const res = NextResponse.json({ access_token: resolved.access_token });
  if (resolved.rotatedCookie) res.cookies.set(GW_COOKIE, resolved.rotatedCookie, GW_COOKIE_OPTIONS);
  return res;
}
