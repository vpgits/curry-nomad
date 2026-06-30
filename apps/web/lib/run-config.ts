import { WORKSPACE_ENABLED } from "./config";
import { getWorkspaceAccessToken } from "./workspace-client";

// localStorage key for the "Author UI" output-mode toggle (owned by the Thread component). Read here
// too so EVERY submit path applies the pref — not just the chat bar.
export const AUTHOR_UI_KEY = "nora.authorUi";

// The per-run config that EVERY submit must carry. Two independent keys ride in config.configurable:
//   - google_access_token: the Workspace capability's per-run Google token (when enabled + connected).
//     The backend `workspace` node reads it and returns the "connect" stub whenever it's ABSENT — it
//     never consults real connection status — so a submit that forgets the token degrades a connected
//     operator to "please connect". The chat bar attached it but edit / regenerate / HITL-resume did
//     not, so reaching a workspace turn via any of those paths hit the stub. This is the single seam.
//   - ui_mode: "authored" when the Author-UI toggle is on, so the analytics path composes an A2UI
//     surface instead of the fixed dashboard.
// Returns a fragment spreadable straight into a stream.submit() options object ({} when there's
// nothing to attach, which spreads to a no-op).
export async function buildSubmitConfig(): Promise<
  { config: { configurable: Record<string, unknown> } } | Record<string, never>
> {
  const configurable: Record<string, unknown> = {};
  if (WORKSPACE_ENABLED) {
    const token = await getWorkspaceAccessToken();
    if (token) configurable.google_access_token = token;
  }
  if (typeof window !== "undefined" && window.localStorage.getItem(AUTHOR_UI_KEY) === "true") {
    configurable.ui_mode = "authored";
  }
  return Object.keys(configurable).length > 0 ? { config: { configurable } } : {};
}
