"use client";

import { useState } from "react";
import { useStream } from "@langchain/langgraph-sdk/react";
import { ArrowUp, ChefHat, CircleAlert, Wrench } from "lucide-react";

import { ApprovalCard } from "@/components/ApprovalCard";
import { VideoBriefCard } from "@/components/VideoBriefCard";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { NoraState, ReviewDecision, ReviewInterrupt, VideoBrief } from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_AEGRA_URL ?? "http://localhost:2026";
const ASSISTANT_ID = process.env.NEXT_PUBLIC_ASSISTANT_ID ?? "nora";

const SUGGESTIONS = [
  "What was our best-selling product in Colombo last quarter?",
  "Make a 30s video ad for it",
  "What's the refund rate on blends?",
];

function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((b: unknown) => (typeof b === "string" ? b : ((b as { text?: string })?.text ?? "")))
      .join("");
  }
  return "";
}

export default function Home() {
  const [input, setInput] = useState("");

  // useStream manages one thread for the session, so the canonical flow (ask → answer →
  // "make a video ad for it" → review → finish) runs on a single thread, and the HITL
  // interrupt is surfaced as `thread.interrupt`.
  const thread = useStream<NoraState>({
    apiUrl: API_URL,
    assistantId: ASSISTANT_ID,
    messagesKey: "messages",
  });

  const interrupt = thread.interrupt?.value as ReviewInterrupt | undefined;
  const isEmpty = thread.messages.length === 0;

  const send = (text: string) => {
    const content = text.trim();
    if (!content || thread.isLoading) return;
    setInput("");
    thread.submit({ messages: [{ type: "human", content }] });
  };

  // Resume the paused marketing workflow with the operator's decision (our custom payload,
  // read by human_review in nodes.py).
  const decide = (decision: ReviewDecision) => {
    thread.submit(undefined, { command: { resume: decision } });
  };

  const error = thread.error
    ? String((thread.error as { message?: string })?.message ?? thread.error)
    : null;

  return (
    <div className="flex h-dvh flex-col">
      <header className="shrink-0 border-b bg-background/80 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center gap-3 px-4 py-3">
          <div className="flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <ChefHat className="size-5" />
          </div>
          <div className="min-w-0">
            <h1 className="text-sm leading-tight font-semibold">
              Nora · <span className="text-muted-foreground">Curry Nomad</span>
            </h1>
            <p className="truncate text-xs text-muted-foreground">
              One assistant, two paradigms — an analytics agent and a marketing workflow.
            </p>
          </div>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-4 py-6">
          {isEmpty && !thread.isLoading ? (
            <EmptyState onPick={send} />
          ) : (
            <div className="flex flex-col gap-6">
              {thread.messages.map((message, idx) => (
                <MessageView key={(message as { id?: string }).id ?? idx} message={message} />
              ))}

              {interrupt && (
                <ApprovalCard payload={interrupt} disabled={thread.isLoading} onDecision={decide} />
              )}

              {thread.isLoading && <ThinkingIndicator />}

              {error && (
                <Alert variant="destructive">
                  <CircleAlert />
                  <AlertTitle>Something went wrong</AlertTitle>
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}
            </div>
          )}
        </div>
      </main>

      <footer className="shrink-0 border-t bg-background/80 backdrop-blur">
        <form
          className="mx-auto flex max-w-3xl items-center gap-2 px-4 py-4"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about the business, or ask for a video ad…"
            disabled={thread.isLoading}
            className="h-11 rounded-xl"
          />
          <Button
            type="submit"
            size="icon"
            disabled={thread.isLoading || !input.trim()}
            className="size-11 shrink-0 rounded-xl"
            aria-label="Send message"
          >
            <ArrowUp className="size-5" />
          </Button>
        </form>
      </footer>
    </div>
  );
}

function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="flex flex-col items-center gap-6 py-16 text-center">
      <div className="flex size-14 items-center justify-center rounded-2xl bg-primary text-primary-foreground">
        <ChefHat className="size-7" />
      </div>
      <div className="space-y-1.5">
        <h2 className="text-xl font-semibold">How can Nora help?</h2>
        <p className="mx-auto max-w-md text-sm text-muted-foreground">
          Ask about the business and the analytics <b>agent</b> answers; ask for an ad and the
          marketing <b>workflow</b> builds a brief — with a human-review gate.
        </p>
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        {SUGGESTIONS.map((s) => (
          <Button
            key={s}
            variant="outline"
            size="sm"
            className="rounded-full"
            onClick={() => onPick(s)}
          >
            {s}
          </Button>
        ))}
      </div>
    </div>
  );
}

function NoraAvatar() {
  return (
    <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
      <ChefHat className="size-4" />
    </div>
  );
}

function ThinkingIndicator() {
  return (
    <div className="flex items-start gap-3">
      <NoraAvatar />
      <div className="flex items-center gap-1 pt-2.5">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="size-1.5 animate-bounce rounded-full bg-muted-foreground/60"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </div>
    </div>
  );
}

function MessageView({ message }: { message: unknown }) {
  const m = message as {
    type: string;
    content: unknown;
    tool_calls?: { name: string; args: Record<string, unknown> }[];
    additional_kwargs?: { video_brief?: VideoBrief };
  };

  if (m.type === "human") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl bg-primary px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap text-primary-foreground">
          {textOf(m.content)}
        </div>
      </div>
    );
  }

  if (m.type === "ai") {
    const text = textOf(m.content);
    const toolCalls = m.tool_calls ?? [];
    const brief = m.additional_kwargs?.video_brief;
    return (
      <div className="flex items-start gap-3">
        <NoraAvatar />
        <div className="min-w-0 flex-1 space-y-2">
          <div className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Nora
          </div>
          {text && (
            <div className="text-sm leading-relaxed whitespace-pre-wrap break-words">{text}</div>
          )}
          {toolCalls.map((tc, i) => (
            <ToolCall key={i} name={tc.name} args={tc.args} />
          ))}
          {brief && <VideoBriefCard brief={brief} />}
        </div>
      </div>
    );
  }

  return null; // tool/system messages from the orchestrator level are hidden
}

function ToolCall({ name, args }: { name: string; args: Record<string, unknown> }) {
  return (
    <div
      className={cn(
        "inline-flex max-w-full items-center gap-1.5 rounded-lg border bg-muted/40 px-2.5 py-1.5",
        "font-mono text-xs text-muted-foreground",
      )}
    >
      <Wrench className="size-3 shrink-0" />
      <span className="truncate">
        {name}({JSON.stringify(args)})
      </span>
    </div>
  );
}
