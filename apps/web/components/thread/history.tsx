"use client";

import { useEffect } from "react";
import { useQueryState } from "nuqs";
import { History, SquarePen } from "lucide-react";
import type { Message, Thread } from "@langchain/langgraph-sdk";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, getContentString } from "@/lib/utils";
import { useThreads } from "@/providers/Thread";

function threadTitle(thread: Thread): string {
  const messages = (thread.values as { messages?: Message[] } | undefined)?.messages;
  const firstHuman = messages?.find((m) => m?.type === "human");
  const text = firstHuman ? getContentString(firstHuman.content) : "";
  return text.trim() || "New conversation";
}

function byRecency(a: Thread, b: Thread): number {
  return (b.updated_at ?? "").localeCompare(a.updated_at ?? "");
}

// The conversation history sidebar. Lists this graph's threads, newest first; the first user
// message is the title (more useful than an id). Selecting a thread drives `threadId` in the URL,
// which StreamProvider reads to reconnect + load that thread's history.
export function ThreadHistory({ onNavigate }: { onNavigate?: () => void }) {
  const { threads, setThreads, getThreads, threadsLoading } = useThreads();
  const [threadId, setThreadId] = useQueryState("threadId");

  useEffect(() => {
    getThreads().then(setThreads).catch(console.error);
  }, [getThreads, setThreads]);

  const newChat = () => {
    setThreadId(null);
    onNavigate?.();
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-3 py-3">
        <span className="flex items-center gap-2 text-sm font-medium">
          <History className="size-4" /> History
        </span>
        <Button variant="ghost" size="icon" className="size-8" title="New chat" onClick={newChat}>
          <SquarePen className="size-4" />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-2">
        {threadsLoading && threads.length === 0 ? (
          <div className="space-y-2 p-1">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full rounded-lg" />
            ))}
          </div>
        ) : threads.length === 0 ? (
          <p className="px-3 py-6 text-center text-xs text-muted-foreground">
            No conversations yet.
          </p>
        ) : (
          <ul className="space-y-1">
            {[...threads].sort(byRecency).map((t) => (
              <li key={t.thread_id}>
                <button
                  type="button"
                  title={threadTitle(t)}
                  onClick={() => {
                    setThreadId(t.thread_id);
                    onNavigate?.();
                  }}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-muted",
                    t.thread_id === threadId && "bg-muted font-medium",
                  )}
                >
                  {t.status === "interrupted" && (
                    <span
                      className="size-1.5 shrink-0 rounded-full bg-amber-500"
                      title="Awaiting review"
                    />
                  )}
                  <span className="truncate">{threadTitle(t)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
