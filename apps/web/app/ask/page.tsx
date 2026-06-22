"use client";

import { Thread } from "@/components/thread";
import { ChatErrorBoundary } from "@/components/thread/error-boundary";

// "Ask Nora" — the chat surface (analytics agent + marketing workflow). StreamProvider is hoisted
// in the root layout, so this route just renders the chat tree; the error boundary stays scoped
// here so a chat render-crash doesn't take down the rest of the app.
export default function AskPage() {
  return (
    <ChatErrorBoundary>
      <Thread />
    </ChatErrorBoundary>
  );
}
