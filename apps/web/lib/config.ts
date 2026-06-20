// Deployment config. Aegra serves the `nora` graph over the Agent Protocol on :2026; the graph
// id doubles as the assistant id (Aegra creates a default assistant for the graph). These are
// build-time public env vars — there is no browser-side secret (Aegra is keyless locally).
export const API_URL = process.env.NEXT_PUBLIC_AEGRA_URL ?? "http://localhost:2026";
export const ASSISTANT_ID = process.env.NEXT_PUBLIC_ASSISTANT_ID ?? "nora";
