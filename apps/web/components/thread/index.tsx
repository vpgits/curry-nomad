"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUp, ChefHat, Square } from "lucide-react";
import type { Message } from "@langchain/langgraph-sdk";

import { AppSidebar } from "@/components/app-sidebar";
import { ApprovalCard } from "@/components/ApprovalCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import type { ReviewDecision, ReviewInterrupt } from "@/lib/types";
import { useStreamContext } from "@/providers/Stream";
import { AssistantMessage, NoraAvatar } from "./messages/ai";
import { HumanMessage } from "./messages/human";

const SUGGESTIONS = [
  "What was our best-selling product in Colombo last quarter?",
  "Make a 30s video ad for it",
  "What's the refund rate on blends?",
];

export function Thread() {
  const stream = useStreamContext();
  const [input, setInput] = useState("");

  const messages = stream.messages.filter((m) => !m.id?.startsWith("do-not-render-"));
  const interrupt = stream.interrupt?.value as ReviewInterrupt | undefined;
  const isLoading = stream.isLoading;
  const isEmpty = messages.length === 0 && !isLoading;

  // The last turn is human (or empty) → the model hasn't started replying yet → show the dots.
  const lastIsHuman = messages.length > 0 && messages[messages.length - 1].type === "human";

  const send = (text: string) => {
    const content = text.trim();
    if (!content) return;
    setInput("");
    stream.submit(
      { messages: [{ type: "human", content }] },
      {
        streamMode: ["values"],
        optimisticValues: (prev) => ({
          ...prev,
          messages: [
            ...(prev.messages ?? []),
            { type: "human", content, id: `tmp-${crypto.randomUUID()}` } as Message,
          ],
        }),
      },
    );
  };

  // Resume the paused marketing workflow with the operator's decision (read by human_review).
  const decide = (decision: ReviewDecision) => {
    stream.submit(undefined, { command: { resume: decision }, streamMode: ["values"] });
  };

  return (
    <SidebarProvider className="h-dvh overflow-hidden">
      <AppSidebar />
      <SidebarInset className="min-w-0">
        <header className="shrink-0 border-b bg-background/80 backdrop-blur">
          <div className="flex items-center gap-2 px-4 py-3">
            <SidebarTrigger className="-ml-1" />
            <Separator orientation="vertical" className="mr-1 data-[orientation=vertical]:h-5" />
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

        <MessageList
          messages={messages}
          isLoading={isLoading}
          lastIsHuman={lastIsHuman}
          interrupt={interrupt}
          isEmpty={isEmpty}
          onDecide={decide}
          onPick={send}
        />

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
              className="h-11 rounded-xl"
            />
            {isLoading ? (
              <Button
                type="button"
                size="icon"
                variant="outline"
                onClick={() => stream.stop()}
                className="size-11 shrink-0 rounded-xl"
                aria-label="Stop"
              >
                <Square className="size-4" />
              </Button>
            ) : (
              <Button
                type="submit"
                size="icon"
                disabled={!input.trim()}
                className="size-11 shrink-0 rounded-xl"
                aria-label="Send message"
              >
                <ArrowUp className="size-5" />
              </Button>
            )}
          </form>
        </footer>
      </SidebarInset>
    </SidebarProvider>
  );
}

function MessageList({
  messages,
  isLoading,
  lastIsHuman,
  interrupt,
  isEmpty,
  onDecide,
  onPick,
}: {
  messages: Message[];
  isLoading: boolean;
  lastIsHuman: boolean;
  interrupt: ReviewInterrupt | undefined;
  isEmpty: boolean;
  onDecide: (decision: ReviewDecision) => void;
  onPick: (text: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);
  const [showScrollButton, setShowScrollButton] = useState(false);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    atBottomRef.current = nearBottom;
    setShowScrollButton(!nearBottom);
  };

  const scrollToBottom = (behavior: ScrollBehavior = "smooth") => {
    endRef.current?.scrollIntoView({ behavior });
    atBottomRef.current = true;
    setShowScrollButton(false);
  };

  // Follow new content (tokens + new messages) only when the user is already at the bottom.
  useEffect(() => {
    if (atBottomRef.current) scrollToBottom("smooth");
  }, [messages, interrupt, isLoading]);

  // A new interrupt only resets the ApprovalCard's local edit state when the script truly changes.
  const interruptKey = interrupt ? JSON.stringify(interrupt.script_beats) : undefined;

  return (
    <div ref={scrollRef} onScroll={onScroll} className="relative min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl px-4 py-6">
        {isEmpty ? (
          <EmptyState onPick={onPick} />
        ) : (
          <div className="flex flex-col gap-6">
            {messages.map((message, idx) => {
              if (message.type === "human") {
                return (
                  <HumanMessage
                    key={message.id ?? idx}
                    message={message}
                    isLoading={isLoading}
                  />
                );
              }
              if (message.type === "ai") {
                return (
                  <AssistantMessage
                    key={message.id ?? idx}
                    message={message}
                    isLoading={isLoading}
                  />
                );
              }
              return null;
            })}

            {interrupt && (
              <ApprovalCard
                key={interruptKey}
                payload={interrupt}
                disabled={isLoading}
                onDecision={onDecide}
              />
            )}

            {isLoading && lastIsHuman && <ThinkingIndicator />}
          </div>
        )}
        <div ref={endRef} />
      </div>

      {showScrollButton && (
        <Button
          size="icon"
          variant="outline"
          onClick={() => scrollToBottom("smooth")}
          className="sticky bottom-4 left-1/2 size-9 -translate-x-1/2 rounded-full shadow-md"
          aria-label="Scroll to bottom"
        >
          <ArrowDown className="size-4" />
        </Button>
      )}
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
          <Button key={s} variant="outline" size="sm" className="rounded-full" onClick={() => onPick(s)}>
            {s}
          </Button>
        ))}
      </div>
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
