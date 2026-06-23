"use client";

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import type { Thread } from "@langchain/langgraph-sdk";

import { API_URL, ASSISTANT_ID, STUDIO_ASSISTANT_ID } from "@/lib/config";
import { aegraAuthHeaders } from "@/lib/auth-headers";
import { createClient } from "./client";

interface ThreadContextType {
  threads: Thread[];
  setThreads: Dispatch<SetStateAction<Thread[]>>;
  getThreads: () => Promise<Thread[]>;
  threadsLoading: boolean;
}

const ThreadContext = createContext<ThreadContextType | undefined>(undefined);

export function ThreadProvider({ children }: { children: ReactNode }) {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [threadsLoading, setThreadsLoading] = useState(false);

  // Aegra tags each thread's metadata with the last graph it ran (`graph_id`). We list BOTH the main
  // `nora` chat and the `nora_a2ui` studio threads (two searches, merged) so the history sidebar
  // shows them together; the sidebar reads each thread's graph_id to route it to /ask vs /studio.
  const getThreads = useCallback(async (): Promise<Thread[]> => {
    setThreadsLoading(true);
    try {
      const client = createClient(API_URL, undefined, await aegraAuthHeaders());
      const [main, studio] = await Promise.all([
        client.threads.search({ metadata: { graph_id: ASSISTANT_ID }, limit: 100 }),
        client.threads.search({ metadata: { graph_id: STUDIO_ASSISTANT_ID }, limit: 100 }),
      ]);
      const seen = new Set<string>();
      return [...main, ...studio].filter((t) => {
        if (seen.has(t.thread_id)) return false;
        seen.add(t.thread_id);
        return true;
      });
    } finally {
      setThreadsLoading(false);
    }
  }, []);

  return (
    <ThreadContext.Provider value={{ threads, setThreads, getThreads, threadsLoading }}>
      {children}
    </ThreadContext.Provider>
  );
}

export function useThreads(): ThreadContextType {
  const ctx = useContext(ThreadContext);
  if (ctx === undefined) {
    throw new Error("useThreads must be used within a ThreadProvider");
  }
  return ctx;
}
