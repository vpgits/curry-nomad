"use client";

import { Thread } from "@/components/thread";
import { ChatErrorBoundary } from "@/components/thread/error-boundary";
import { StreamProvider } from "@/providers/Stream";

// ThreadProvider + the nuqs Suspense boundary live in the root layout (shared by every page so
// the AppShell sidebar works app-wide). StreamProvider owns the useStream connection for the
// thread selected via the URL's threadId, so it stays page-local to the custom chat UI.
export default function Home() {
  return (
    <ChatErrorBoundary>
      <StreamProvider>
        <Thread />
      </StreamProvider>
    </ChatErrorBoundary>
  );
}
