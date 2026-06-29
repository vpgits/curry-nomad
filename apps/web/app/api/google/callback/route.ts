import { NextResponse, type NextRequest } from "next/server";

import { auth } from "@/auth";
import {
  GW_COOKIE,
  GW_COOKIE_OPTIONS,
  GW_STATE_COOKIE,
  encryptTokens,
  exchangeCodeForTokens,
} from "@/lib/google";

// Finish the incremental grant: verify the one-time CSRF state, exchange the code for tokens, and
// stash them in an encrypted, httpOnly, session-scoped cookie. Then bounce back to /ask. Best-effort
// — any failure just lands on /ask?gw=error and the operator can retry.
//
// This stays a GET because Google redirects the browser here with a GET — it cannot be a POST. It is
// safe because the write is gated on a one-time, session-bound `state` (planted in /connect) plus
// Google's single-use authorization `code`, so a prefetch or forged request can't trigger it. See
// react-doctor nextjs-no-side-effect-in-get-handler case (C): OAuth callbacks keep GET and make the
// write single-use, rather than switching to POST (which would break Google's redirect).
export async function GET(req: NextRequest) {
  const origin = req.nextUrl.origin;
  const session = await auth();
  if (!session) return NextResponse.redirect(new URL("/", origin));

  // Build the error/exit redirect and consume the one-time state cookie on every outcome, so a state
  // is never reusable (single-use). Cleared at the cookie's own path so the deletion actually lands.
  const exit = (to: string) => {
    const out = NextResponse.redirect(new URL(to, origin));
    out.cookies.delete({ name: GW_STATE_COOKIE, path: "/api/google" });
    return out;
  };

  // CSRF guard: the value Google echoed back must match the state we planted in /connect.
  const state = req.nextUrl.searchParams.get("state");
  const expectedState = req.cookies.get(GW_STATE_COOKIE)?.value;
  if (!state || !expectedState || state !== expectedState) return exit("/ask?gw=error");

  const code = req.nextUrl.searchParams.get("code");
  if (!code) return exit("/ask?gw=error");

  const tok = await exchangeCodeForTokens(code);
  if (!tok) return exit("/ask?gw=error");

  const cookieValue = await encryptTokens(tok);
  const out = exit("/ask?gw=connected");
  out.cookies.set(GW_COOKIE, cookieValue, GW_COOKIE_OPTIONS);
  return out;
}
