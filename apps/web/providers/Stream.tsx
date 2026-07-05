"use client";

import { createContext, use, useRef, type ReactNode } from "react";
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

  // Guard against the marketing subgraph transiently blanking the thread mid-stream (see below).
  const guardedStream = useSubgraphBlankGuard(stream);

  return <StreamContext.Provider value={guardedStream}>{children}</StreamContext.Provider>;
}

// Count human turns in a message list — the stable anchor the blank-guard keys on (see below).
function countHumans(messages: StreamContextType["messages"] | undefined): number {
  if (!messages) return 0;
  let n = 0;
  for (const m of messages) if (m.type === "human") n += 1;
  return n;
}

// ── Blank-guard for imperative-subgraph streaming ──────────────────────────────────────────────
// The marketing capability is an imperative subgraph whose state is DISJOINT from the chat — it has
// no `messages` channel (see MarketingState). We submit with `streamSubgraphs: true` because the
// analytics AGENT is a real subgraph node and its tokens must stream in live. The side effect: the
// marketing WORKFLOW's namespaced `values|marketing:…` snapshots also reach the client, and the
// langgraph-sdk stream path applies each one as the WHOLE thread state. Those frames carry no
// `messages` and no `ui`, so mid-run the conversation and its gen-UI cards blank out until the next
// root snapshot restores them — the reported "/ask goes blank while marketing runs".
//
// Root snapshots only ever GROW the human turns (add_messages is append-only), so a mid-run snapshot
// with FEWER human turns than this run started with is a foreign subgraph frame, not real root state
// — hold the last authoritative snapshot until root state returns. Analytics never trips this: it is
// a real subgraph node that SHARES the `messages` channel, so its frames keep every human turn.
// Refs (not state) are load-bearing here: this is the canonical "remember the last snapshot across
// renders WITHOUT re-rendering" pattern — the SDK's own useStream writes refs in render the same way.
// Holding this in state would fire an extra render per streamed token. The rule doesn't model this
// last-value-memory pattern, so it's disabled for the whole (small, self-contained) hook.
/* eslint-disable react-hooks/refs -- last-value memory, intentionally read/written in render */
function useSubgraphBlankGuard(stream: StreamContextType): StreamContextType {
  const heldMessages = useRef(stream.messages);
  const heldValues = useRef(stream.values);
  const baselineHumans = useRef(0);
  const wasLoading = useRef(false);
  // The latest SDK stream, plus ONE stable proxy that reads it. Identity stability is load-bearing:
  // returning a fresh `new Proxy` every render made LoadExternalComponent's `stream` prop change each
  // render, so its subscription to the SDK's UI StreamManager (a useSyncExternalStore) re-subscribed
  // every render → notifyListeners → forceStoreRerender → re-render → re-subscribe → ... = "Maximum
  // update depth exceeded". It only surfaced once the workspace subgraph started streaming and
  // tripping the clobber path. A memoized proxy reading refs keeps a CONSTANT identity while still
  // reflecting live values.
  const latestStream = useRef(stream);
  latestStream.current = stream;
  const blankProxy = useRef<StreamContextType | null>(null);

  const humans = countHumans(stream.messages);
  // A run just started or just settled → this snapshot is authoritative; re-baseline the human
  // count (also covers edit/branch-switch, which can legitimately land on a shorter history).
  if (stream.isLoading !== wasLoading.current) baselineHumans.current = humans;
  wasLoading.current = stream.isLoading;

  const clobbered = stream.isLoading && humans < baselineHumans.current;
  if (!clobbered) {
    baselineHumans.current = Math.max(baselineHumans.current, humans);
    heldMessages.current = stream.messages;
    heldValues.current = stream.values;
    return stream; // steady state: pass the SDK object straight through, untouched.
  }

  // Clobber: shim `messages`/`values` back to the last good snapshot via a SINGLE memoized proxy
  // whose identity stays constant across the clobber's many render frames (see note above). The traps
  // read refs (latest stream + frozen snapshots), so a fixed proxy object still reflects live values;
  // `s` as receiver keeps the SDK's closure-based getters intact, and the ownKeys/descriptor traps
  // forward so spreads/inspection still see the real shape.
  if (blankProxy.current === null) {
    blankProxy.current = new Proxy({} as StreamContextType, {
      get(_t, prop) {
        if (prop === "messages") return heldMessages.current;
        if (prop === "values") return heldValues.current;
        const s = latestStream.current as object;
        return Reflect.get(s, prop, s);
      },
      has(_t, prop) {
        return prop in (latestStream.current as object);
      },
      ownKeys() {
        return Reflect.ownKeys(latestStream.current as object);
      },
      getOwnPropertyDescriptor(_t, prop) {
        const d = Reflect.getOwnPropertyDescriptor(latestStream.current as object, prop);
        // Proxy invariant: a descriptor reported for a key absent on the (empty) target must be
        // configurable, else the trap throws.
        if (d) d.configurable = true;
        return d;
      },
    });
  }
  return blankProxy.current;
}
/* eslint-enable react-hooks/refs */

export function useStreamContext(): StreamContextType {
  const ctx = use(StreamContext);
  if (ctx === undefined) {
    throw new Error("useStreamContext must be used within a StreamProvider");
  }
  return ctx;
}
