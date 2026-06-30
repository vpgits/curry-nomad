import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { GW_COOKIE } from "@/lib/google";

// Drops the Google Workspace grant (the encrypted gw_tokens cookie). Called on sign-out so logging
// out clears Plane 2 too — a fresh login then re-runs the "Connect Google Workspace" grant.
// Require a session: without it, a cross-site or unauthenticated POST could force-clear a victim's
// grant (forced re-consent). `sameSite:lax` on the session cookie + this check make that a non-issue.
export async function POST() {
  const session = await auth();
  if (!session) return NextResponse.json({ ok: false }, { status: 401 });
  const res = NextResponse.json({ ok: true });
  res.cookies.delete(GW_COOKIE);
  return res;
}
