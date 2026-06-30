import { NextResponse, type NextRequest } from "next/server";

import { auth } from "@/auth";
import { GW_COOKIE, GW_COOKIE_OPTIONS, resolveAccessToken } from "@/lib/google";

// Has this operator connected their Google Workspace? Drives the "Connect" affordance in the UI.
// Reports REAL token validity (decrypt + refresh-viability), not mere cookie presence — otherwise a
// dead grant would show "connected" while every token fetch returns null and the agent stubs out.
export async function GET(req: NextRequest) {
  const session = await auth();
  if (!session) return NextResponse.json({ connected: false });

  const raw = req.cookies.get(GW_COOKIE)?.value;
  if (!raw) return NextResponse.json({ connected: false });

  const resolved = await resolveAccessToken(raw);
  if (!resolved) {
    // Stale/unusable cookie → report disconnected AND clear it, so the UI prompts a reconnect and the
    // "connected but stubs out" mismatch can't persist for days.
    const res = NextResponse.json({ connected: false });
    res.cookies.delete(GW_COOKIE);
    return res;
  }

  const res = NextResponse.json({ connected: true });
  // Persist a refresh that happened during the check so the next token fetch reuses it.
  if (resolved.rotatedCookie) res.cookies.set(GW_COOKIE, resolved.rotatedCookie, GW_COOKIE_OPTIONS);
  return res;
}
