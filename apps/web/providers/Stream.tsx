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

import { API_URL, ASSISTANT_ID } from "@/lib/config";
import type { NoraState, NoraUpdate } from "@/lib/types";
import { sleep, tagThread } from "@/lib/threads";
import { useThreads } from "./Thread";

// Instantiation expression (TS 4.7+): pin the generic hook to our state/update shape once.
const useTypedStream = useStream<
  NoraState,
  { UpdateType: NoraUpdate; CustomEventType: UIMessage | RemoveUIMessage }
>;
type StreamContextType = ReturnType<typeof useTypedStream>;

const StreamContext = createContext<StreamContextType | undefined>(undefined);

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
      // A just-created thread isn't immediately searchable; after a beat, tag it (title from its
      // first message), then refetch the list so the new thread shows up labelled.
      sleep()
        .then(() => tagThread(id))
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
