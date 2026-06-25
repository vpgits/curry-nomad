import type { Message } from "@langchain/langgraph-sdk";

import { API_URL, ASSISTANT_ID, AUTH_REQUIRED } from "@/lib/config";
import { aegraAuthHeaders } from "@/lib/auth-headers";
import { getContentString } from "@/lib/utils";
import { createClient } from "@/providers/client";

export const sleep = (ms = 1000) => new Promise((resolve) => setTimeout(resolve, ms));

// Stamp a title (from the first user message) onto a thread's metadata once, after its first run.
// The history sidebar reads it back to label each thread. Aegra's /threads/search returns no state
// values, so the title can't be derived at list time — we read it from thread state here. graph_id
// is re-sent so the search filter survives whether Aegra merges or replaces metadata on update;
// pass the studio graph id for /studio threads so they stay scoped to their own graph.
export async function tagThread(id: string, graphId: string = ASSISTANT_ID): Promise<void> {
  const headers = await aegraAuthHeaders();
  if (AUTH_REQUIRED && !headers.Authorization) return; // not signed in → skip (would 401)
  const client = createClient(API_URL, undefined, headers);
  const state = await client.threads.getState(id);
  const messages = (state.values as { messages?: Message[] } | undefined)?.messages ?? [];
  const firstHuman = messages.find((m) => m?.type === "human");
  const title = firstHuman ? getContentString(firstHuman.content).trim().slice(0, 100) : "";
  await client.threads.update(id, {
    metadata: { graph_id: graphId, ...(title ? { title } : {}) },
  });
}
