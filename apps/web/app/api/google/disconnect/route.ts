import { NextResponse } from "next/server";

import { GW_COOKIE } from "@/lib/google";

// Drops the Google Workspace grant (the encrypted gw_tokens cookie). Called on sign-out so logging
// out clears Plane 2 too — a fresh login then re-runs the "Connect Google Workspace" grant.
export async function POST() {
  const res = NextResponse.json({ ok: true });
  res.cookies.delete(GW_COOKIE);
  return res;
}
