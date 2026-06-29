// Deployment config. Aegra serves the `nora` graph over the Agent Protocol on :2026; the graph id
// doubles as the assistant id (Aegra creates a default assistant for the graph). These are
// build-time public env vars — there is no browser-side secret (Aegra is keyless locally).
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:2026";
export const ASSISTANT_ID = process.env.NEXT_PUBLIC_ASSISTANT_ID ?? "nora";

// The deterministic operations system (inventory + orders + delivery routing) is served by a
// separate FastAPI app — `uv run --extra operations uvicorn nora.operations.api:app --port 8000`.
// The /inventory page talks to it directly over REST; no agent / Aegra involved.
export const OPS_API_URL = process.env.NEXT_PUBLIC_OPS_API_URL ?? "http://localhost:8000";

// Gates the optional Google Workspace capability's UI (the "Connect Google Workspace" affordance and
// the per-run token fetch). Mirrors the backend's NORA_WORKSPACE_ENABLED flag; OFF by default.
export const WORKSPACE_ENABLED = process.env.NEXT_PUBLIC_WORKSPACE_ENABLED === "true";

// When true, the frontend requires a signed-in session before it calls Aegra — matching the backend's
// AUTH_TYPE=custom. The shared sidebar/chat are gated on sign-in instead of 401-ing. OFF by default so
// the keyless (AUTH_TYPE=noop) path is completely unchanged.
export const AUTH_REQUIRED = process.env.NEXT_PUBLIC_AUTH_REQUIRED === "true";
