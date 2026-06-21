import { Client } from "@langchain/langgraph-sdk";

// One SDK client per call site (thread search). useStream manages its own internally.
// Aegra is keyless in local/dev; apiKey stays optional for when auth handlers are enabled.
export function createClient(apiUrl: string, apiKey?: string) {
  return new Client({ apiUrl, apiKey });
}
