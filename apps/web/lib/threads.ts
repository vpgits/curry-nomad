import type { Message } from "@langchain/langgraph-sdk";

import { API_URL, ASSISTANT_ID } from "@/lib/config";
import { getContentString } from "@/lib/utils";
import { createClient } from "@/providers/client";

export const sleep = (ms = 1000) => new Promise((resolve) => setTimeout(resolve, ms));

// Stamp a title (from the first user message) onto a thread's metadata once, after its first run.
// The history sidebar reads it back to label each thread. The server's /threads/search returns no state
// values, so the title can't be derived at list time — we read it from thread state here. graph_id
// is re-sent so the search filter survives whether the server merges or replaces metadata on update.
export async function tagThread(id: string): Promise<void> {
  const client = createClient(API_URL);
  const state = await client.threads.getState(id);
  const messages = (state.values as { messages?: Message[] } | undefined)?.messages ?? [];
  const firstHuman = messages.find((m) => m?.type === "human");
  const title = firstHuman ? getContentString(firstHuman.content).trim().slice(0, 100) : "";
  await client.threads.update(id, {
    metadata: { graph_id: ASSISTANT_ID, ...(title ? { title } : {}) },
  });
}
