import { NextResponse, type NextRequest } from "next/server";

import { auth } from "@/auth";
import { GW_COOKIE } from "@/lib/google";

// Has this operator connected their Google Workspace? Drives the "Connect" affordance in the UI.
export async function GET(req: NextRequest) {
  const session = await auth();
  if (!session) return NextResponse.json({ connected: false });
  return NextResponse.json({ connected: Boolean(req.cookies.get(GW_COOKIE)?.value) });
}
