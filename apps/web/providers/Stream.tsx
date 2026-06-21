"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useStream } from "@langchain/langgraph-sdk/react";
import {
  uiMessageReducer,
  type RemoveUIMessage,
  type UIMessage,
} from "@langchain/langgraph-sdk/react-ui";
import { useQueryState } from "nuqs";
import { toast } from "sonner";
import type { Message } from "@langchain/langgraph-sdk";

import { API_URL, ASSISTANT_ID } from "@/lib/config";
import { getContentString } from "@/lib/utils";
import type { NoraState, NoraUpdate } from "@/lib/types";
import { createClient } from "./client";
import { useThreads } from "./Thread";

// Aegra's /threads/search returns no state values, so we can't derive a title from messages at
// list time. Instead, stamp the first user message onto the thread's metadata once, at creation,
// and read it back in the history sidebar. (graph_id is re-sent so the search filter survives
// whether Aegra merges or replaces metadata on update.)
async function titleThread(id: string): Promise<void> {
  const client = createClient(API_URL);
  const state = await client.threads.getState(id);
  const messages = (state.values as { messages?: Message[] } | undefined)?.messages ?? [];
  const firstHuman = messages.find((m) => m?.type === "human");
  const title = firstHuman ? getContentString(firstHuman.content).trim().slice(0, 100) : "";
  if (title) {
    await client.threads.update(id, { metadata: { graph_id: ASSISTANT_ID, title } });
  }
}

// Instantiation expression (TS 4.7+): pin the generic hook to our state/update shape once.
const useTypedStream = useStream<
  NoraState,
  { UpdateType: NoraUpdate; CustomEventType: UIMessage | RemoveUIMessage }
>;
type StreamContextType = ReturnType<typeof useTypedStream>;

const StreamContext = createContext<StreamContextType | undefined>(undefined);

const sleep = (ms = 1000) => new Promise((resolve) => setTimeout(resolve, ms));

export function StreamProvider({ children }: { children: ReactNode }) {
  // threadId lives in the URL so a conversation is shareable/bookmarkable; null = a fresh thread.
  const [threadId, setThreadId] = useQueryState("threadId");
  const { getThreads, setThreads } = useThreads();

  const stream = useTypedStream({
    apiUrl: API_URL,
    assistantId: ASSISTANT_ID,
    threadId: threadId ?? null,
    messagesKey: "messages",
    // Load prior messages + per-message checkpoint metadata (needed for edit/regenerate branching).
    fetchStateHistory: true,
    onThreadId: (id) => {
      setThreadId(id);
      // A just-created thread isn't immediately searchable; after a beat, title it from its first
      // message, then refetch the list so the new (titled) thread shows up.
      sleep()
        .then(() => titleThread(id))
        .then(() => getThreads())
        .then(setThreads)
        .catch(console.error);
    },
    onError: (err) => {
      toast.error("Something went wrong", {
        description: err instanceof Error ? err.message : String(err),
      });
    },
    // Generative UI: fold streamed push_ui_message events into `values.ui` so the dashboard can
    // render progressively (the values stream also carries the final `ui` channel).
    onCustomEvent: (event, options) => {
      options.mutate((prev) => ({
        ...prev,
        ui: uiMessageReducer(prev.ui ?? [], event),
      }));
    },
  });

  return <StreamContext.Provider value={stream}>{children}</StreamContext.Provider>;
}

export function useStreamContext(): StreamContextType {
  const ctx = useContext(StreamContext);
  if (ctx === undefined) {
    throw new Error("useStreamContext must be used within a StreamProvider");
  }
  return ctx;
}
