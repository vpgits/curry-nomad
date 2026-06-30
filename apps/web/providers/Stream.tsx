"use client";

import { createContext, use, type ReactNode } from "react";
import { useStream } from "@langchain/langgraph-sdk/react";
import {
  uiMessageReducer,
  type RemoveUIMessage,
  type UIMessage,
} from "@langchain/langgraph-sdk/react-ui";
import { useQueryState } from "nuqs";
import { useSession } from "next-auth/react";
import { toast } from "sonner";

import { API_URL, ASSISTANT_ID, AUTH_REQUIRED } from "@/lib/config";
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
  // When the operator is signed in, attach their minted Aegra token so the backend (AUTH_TYPE=custom)
  // identifies them and scopes threads. Omitted when signed out / auth off → the keyless path is unchanged.
  const { data: session, status } = useSession();
  const aegraToken = session?.aegraToken;
  // Custom-auth mode: stay inert until signed in — don't fetch a thread's history without a token
  // (it would 401). On sign-in the session updates and the real threadId flows back in.
  const blocked = AUTH_REQUIRED && status !== "authenticated";

  const stream = useTypedStream({
    apiUrl: API_URL,
    assistantId: ASSISTANT_ID,
    ...(aegraToken ? { defaultHeaders: { Authorization: `Bearer ${aegraToken}` } } : {}),
    threadId: blocked ? null : (threadId ?? null),
    messagesKey: "messages",
    // Load prior messages + per-message checkpoint metadata (needed for edit/regenerate branching).
    // Use a numeric limit, NOT `true`: `true` caps the fetched history at the SDK default of 10
    // checkpoints, but one Nora turn burns several (route → capability → tool loop → dashboard), so
    // for any non-trivial conversation the window doesn't reach an older turn's fork checkpoint.
    // Editing/regenerating an older message then can't resolve `firstSeenState.parent_checkpoint`
    // and silently runs from HEAD — the new turn appends at the end instead of forking in place.
    fetchStateHistory: { limit: 1000 },
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
  const ctx = use(StreamContext);
  if (ctx === undefined) {
    throw new Error("useStreamContext must be used within a StreamProvider");
  }
  return ctx;
}
