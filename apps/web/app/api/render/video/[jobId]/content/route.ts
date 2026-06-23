// Streams a finished OpenRouter video through the web server (the browser can't hit OpenRouter's
// content endpoint directly — it needs the Bearer key, which stays server-side). The card points a
// <video src> here once the sibling status route reports `completed`.
const OPENROUTER_BASE = process.env.OPENROUTER_BASE_URL ?? "https://openrouter.ai/api/v1";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ jobId: string }> },
) {
  const { jobId } = await params;
  const key = process.env.OPENROUTER_API_KEY;
  if (!key) return new Response("OPENROUTER_API_KEY is not set on the web server", { status: 500 });

  const upstream = await fetch(
    `${OPENROUTER_BASE}/videos/${encodeURIComponent(jobId)}/content?index=0`,
    { headers: { Authorization: `Bearer ${key}` }, cache: "no-store" },
  );
  if (!upstream.ok || !upstream.body) {
    return new Response("video not ready", { status: 502 });
  }
  return new Response(upstream.body, {
    headers: {
      "Content-Type": upstream.headers.get("Content-Type") ?? "video/mp4",
      "Cache-Control": "private, max-age=3600",
    },
  });
}
