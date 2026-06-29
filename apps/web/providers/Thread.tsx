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

import { API_URL, ASSISTANT_ID, AUTH_REQUIRED } from "@/lib/config";
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

  // Aegra tags each thread's metadata with the last graph it ran (`graph_id`). We list the main
  // `nora` chat threads so the history sidebar shows them; all open on /ask.
  const getThreads = useCallback(async (): Promise<Thread[]> => {
    setThreadsLoading(true);
    try {
      const headers = await aegraAuthHeaders();
      // Custom-auth mode: don't hit Aegra (it would 401) until the operator is signed in.
      if (AUTH_REQUIRED && !headers.Authorization) return [];
      const client = createClient(API_URL, undefined, headers);
      return await client.threads.search({ metadata: { graph_id: ASSISTANT_ID }, limit: 100 });
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
