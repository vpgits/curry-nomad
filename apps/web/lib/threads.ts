import type { Message } from "@langchain/langgraph-sdk";

import { API_URL, ASSISTANT_ID } from "@/lib/config";
import { getContentString } from "@/lib/utils";
import { createClient } from "@/providers/client";

// Both chat surfaces (`/` useStream and `/copilot` CopilotKit) run the SAME `nora` graph on Aegra,
// so Aegra stamps every thread's metadata with the same `graph_id`. To tell them apart in the
// shared history sidebar we additionally write a `source` marker at creation — see tagThread.
export type ThreadSource = "nora" | "copilot";

export const sleep = (ms = 1000) => new Promise((resolve) => setTimeout(resolve, ms));

// Which surface created a thread. Defaults to "nora": threads created before source tagging existed
// have no marker, and the `/` UI can render any thread's state, so it's the safe fallback.
export function threadSource(metadata: unknown): ThreadSource {
  const source = (metadata as { source?: unknown } | undefined)?.source;
  return source === "copilot" ? "copilot" : "nora";
}

// Stamp `source` (+ a title from the first user message) onto a thread's metadata once, after its
// first run. The history sidebar reads both back to label each thread and route a click to the
// surface that created it. Aegra's /threads/search returns no state values, so the title can't be
// derived at list time — we read it from thread state here. graph_id is re-sent so the search
// filter survives whether Aegra merges or replaces metadata on update.
export async function tagThread(id: string, source: ThreadSource): Promise<void> {
  const client = createClient(API_URL);
  const state = await client.threads.getState(id);
  const messages = (state.values as { messages?: Message[] } | undefined)?.messages ?? [];
  const firstHuman = messages.find((m) => m?.type === "human");
  const title = firstHuman ? getContentString(firstHuman.content).trim().slice(0, 100) : "";
  await client.threads.update(id, {
    metadata: { graph_id: ASSISTANT_ID, source, ...(title ? { title } : {}) },
  });
}
