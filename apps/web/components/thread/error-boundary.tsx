"use client";

import { Component, type ReactNode } from "react";
import { CircleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";

// A last-resort boundary so a render error in the chat tree doesn't white-screen the whole app.
// (Streaming/network errors are surfaced via sonner toasts; this catches React render crashes.)
export class ChatErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-dvh flex-col items-center justify-center gap-4 p-6 text-center">
          <CircleAlert className="size-8 text-destructive" />
          <div className="space-y-1">
            <h2 className="text-lg font-semibold">The chat hit an error</h2>
            <p className="max-w-md text-sm text-muted-foreground">{this.state.error.message}</p>
          </div>
          <Button onClick={() => this.setState({ error: null })}>Try again</Button>
        </div>
      );
    }
    return this.props.children;
  }
}
