// Deployment config. Aegra serves the `nora` graph over the Agent Protocol on :2026; the graph id
// doubles as the assistant id (Aegra creates a default assistant for the graph). These are
// build-time public env vars — there is no browser-side secret (Aegra is keyless locally).
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:2026";
export const ASSISTANT_ID = process.env.NEXT_PUBLIC_ASSISTANT_ID ?? "nora";
// The A2UI "studio" showcase runs a second graph (a2ui_studio.py:make_a2ui_graph). Its threads are
// tagged with this graph_id so the history sidebar can list them and route them back to /studio.
export const STUDIO_ASSISTANT_ID =
  process.env.NEXT_PUBLIC_STUDIO_ASSISTANT_ID ?? "nora_a2ui";

// The deterministic operations system (inventory + orders + delivery routing) is served by a
// separate FastAPI app — `uv run --extra operations uvicorn nora.operations.api:app --port 8000`.
// The /inventory page talks to it directly over REST; no agent / Aegra involved.
export const OPS_API_URL = process.env.NEXT_PUBLIC_OPS_API_URL ?? "http://localhost:8000";

// Gates the optional Google Workspace capability's UI (the "Connect Google Workspace" affordance and
// the per-run token fetch). Mirrors the backend's NORA_WORKSPACE_ENABLED flag; OFF by default.
export const WORKSPACE_ENABLED = process.env.NEXT_PUBLIC_WORKSPACE_ENABLED === "true";
