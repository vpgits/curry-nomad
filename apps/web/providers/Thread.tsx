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

import { API_URL, ASSISTANT_ID } from "@/lib/config";
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

  // The server tags each thread's metadata with the last graph it ran (`graph_id`). Filtering on it
  // scopes the history to this deployment's graph.
  const getThreads = useCallback(async (): Promise<Thread[]> => {
    setThreadsLoading(true);
    try {
      const client = createClient(API_URL);
      return await client.threads.search({
        metadata: { graph_id: ASSISTANT_ID },
        limit: 100,
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
