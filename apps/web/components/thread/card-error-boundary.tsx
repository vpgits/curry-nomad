"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";
import { CircleAlert, RotateCcw } from "lucide-react";

// A GRANULAR, inline error boundary for a single streamed gen-UI card (or one assistant turn).
// Unlike the page-root ChatErrorBoundary — whose h-dvh fallback blanks the WHOLE screen — this
// renders a small notice IN PLACE, so a card that throws on a partial/streaming payload can't take
// down the chat. `resetKeys` gives auto-recovery: when the streamed props change (e.g. the rest of
// the payload finally arrives), the boundary clears its error and re-renders the child, which then
// succeeds on the now-complete data. (The known thrower was PostBriefCard dereferencing required
// fields — brief.shots.length, brief.hashtags.map — before they streamed in.)
export class CardErrorBoundary extends Component<
  { children: ReactNode; resetKeys?: unknown[]; label?: string },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(
      "%c[gen-ui-debug] CardErrorBoundary caught (contained) label=" + String(this.props.label),
      "color:#e67e22;font-weight:bold",
      error,
      "\ncomponentStack:",
      info?.componentStack,
    );
  }

  componentDidUpdate(prev: { resetKeys?: unknown[] }) {
    if (this.state.error && !shallowEqualKeys(prev.resetKeys, this.props.resetKeys)) {
      this.setState({ error: null });
    }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="rounded-[13px] border border-destructive/30 bg-destructive/5 px-[15px] py-3 text-[13px] leading-[1.5]">
          <div className="flex items-center gap-2 font-medium text-destructive">
            <CircleAlert className="size-4 shrink-0" />
            <span>Couldn&apos;t render {this.props.label ?? "this card"}</span>
          </div>
          <p className="mt-1 break-words text-muted-foreground">{this.state.error.message}</p>
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            className="mt-2 inline-flex items-center gap-1 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <RotateCcw className="size-3.5" />
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

function shallowEqualKeys(a?: unknown[], b?: unknown[]) {
  if (a === b) return true;
  if (!a || !b || a.length !== b.length) return false;
  return a.every((value, i) => Object.is(value, b[i]));
}
