// Fetch the operator's current Google access token (refreshed server-side) to attach to a chat run.
// Returns null when not connected / not signed in, so the workspace node degrades to a "connect"
// reply rather than failing.
export async function getWorkspaceAccessToken(): Promise<string | null> {
  try {
    const res = await fetch("/api/google/token", { cache: "no-store" });
    if (!res.ok) return null;
    const data = await res.json();
    return typeof data.access_token === "string" ? data.access_token : null;
  } catch {
    return null;
  }
}
