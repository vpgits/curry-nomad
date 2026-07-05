import { WORKSPACE_ENABLED } from "./config";
import { getWorkspaceAccessToken } from "./workspace-client";

// localStorage key for the "Author UI" output-mode preference. Module-private: it's now read only
// here (in buildSubmitConfig), so every submit path applies the persisted pref.
const AUTHOR_UI_KEY = "nora.authorUi";

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
  // Dynamic per-run context the backend folds into the supervisor + workspace prompts AFTER their
  // static (cacheable) prefix — so temporal requests resolve without pestering the operator ("what
  // timezone is 'today 5pm'?"). The BROWSER is authoritative for "now" and "where"; the server's
  // clock/timezone isn't the operator's. Sent every turn (cheap; the backend ignores it where it
  // doesn't apply, e.g. analytics, which uses its fixed data_as_of).
  if (typeof window !== "undefined") {
    configurable.client_now = new Date().toISOString();
    try {
      configurable.client_timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    } catch {
      /* Intl unavailable — skip; the backend still has client_now (UTC) */
    }
  }
  return Object.keys(configurable).length > 0 ? { config: { configurable } } : {};
}
