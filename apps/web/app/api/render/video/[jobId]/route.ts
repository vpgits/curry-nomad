import { NextResponse } from "next/server";

// Server-side proxy for OpenRouter video-job status. The browser polls this (same-origin) instead
// of OpenRouter directly, so the OPENROUTER_API_KEY stays on the server (no NEXT_PUBLIC_ prefix —
// route handlers run server-side only). The marketing_render card polls until `status` is terminal,
// then streams the finished clip from the sibling /content route.
const OPENROUTER_BASE = process.env.OPENROUTER_BASE_URL ?? "https://openrouter.ai/api/v1";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ jobId: string }> },
) {
  const { jobId } = await params;
  const key = process.env.OPENROUTER_API_KEY;
  if (!key) {
    return NextResponse.json(
      { status: "error", error: "OPENROUTER_API_KEY is not set on the web server" },
      { status: 500 },
    );
  }
  const res = await fetch(`${OPENROUTER_BASE}/videos/${encodeURIComponent(jobId)}`, {
    headers: { Authorization: `Bearer ${key}` },
    cache: "no-store",
  });
  if (!res.ok) {
    return NextResponse.json(
      { status: "error", error: `OpenRouter responded ${res.status}` },
      { status: 502 },
    );
  }
  const data = await res.json();
  return NextResponse.json({ id: data.id ?? jobId, status: data.status ?? "unknown" });
}
