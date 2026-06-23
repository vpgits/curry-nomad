import { Client } from "@langchain/langgraph-sdk";

// One SDK client per call site (thread search). useStream manages its own internally.
// Aegra is keyless in local/dev; apiKey/defaultHeaders stay optional for when auth is enabled
// (AUTH_TYPE=custom) — callers pass an `Authorization: Bearer <session token>` via defaultHeaders.
export function createClient(
  apiUrl: string,
  apiKey?: string,
  defaultHeaders?: Record<string, string>,
) {
  return new Client({ apiUrl, apiKey, defaultHeaders });
}
