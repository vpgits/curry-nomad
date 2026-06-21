// Deployment config. `langgraph dev` serves the `nora` graph over the Agent Protocol on :2024; the
// graph id doubles as the assistant id (the server creates a default assistant for the graph). These
// are build-time public env vars — there is no browser-side secret (the dev server is keyless locally).
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:2024";
export const ASSISTANT_ID = process.env.NEXT_PUBLIC_ASSISTANT_ID ?? "nora";
