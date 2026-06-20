"use client";

import { Suspense } from "react";

import { Thread } from "@/components/thread";
import { ChatErrorBoundary } from "@/components/thread/error-boundary";
import { StreamProvider } from "@/providers/Stream";
import { ThreadProvider } from "@/providers/Thread";

// Provider order matters: ThreadProvider is outermost (thread selection drives which stream to
// connect to), then StreamProvider (owns the useStream connection for the selected thread).
// Suspense wraps the tree because nuqs' URL state reads useSearchParams.
export default function Home() {
  return (
    <Suspense fallback={null}>
      <ChatErrorBoundary>
        <ThreadProvider>
          <StreamProvider>
            <Thread />
          </StreamProvider>
        </ThreadProvider>
      </ChatErrorBoundary>
    </Suspense>
  );
}
