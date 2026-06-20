"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useStream } from "@langchain/langgraph-sdk/react";
import { useQueryState } from "nuqs";
import { toast } from "sonner";

import { API_URL, ASSISTANT_ID } from "@/lib/config";
import type { NoraState, NoraUpdate } from "@/lib/types";
import { useThreads } from "./Thread";

// Instantiation expression (TS 4.7+): pin the generic hook to our state/update shape once.
const useTypedStream = useStream<NoraState, { UpdateType: NoraUpdate }>;
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
      // A just-created thread isn't immediately searchable; refetch the list after a beat.
      sleep().then(() => getThreads().then(setThreads).catch(console.error));
    },
    onError: (err) => {
      toast.error("Something went wrong", {
        description: err instanceof Error ? err.message : String(err),
      });
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
