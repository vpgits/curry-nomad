"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useQueryState } from "nuqs";
import { ArrowDown, ArrowUp, Square } from "lucide-react";
import type { Message } from "@langchain/langgraph-sdk";

import { AppShell } from "@/components/app-shell";
import { ConceptPicker } from "@/components/ConceptPicker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { MarketingInterrupt } from "@/lib/types";
import { useStreamContext } from "@/providers/Stream";
import { AskNoraModeLane } from "./AskNoraModeLane";
import { AssistantMessage, NoraAvatar } from "./messages/ai";
import { HumanMessage } from "./messages/human";

const SUGGESTIONS = [
  "What was our best-selling product in Colombo last quarter?",
  "Make a 30s video ad for it",
  "What's the refund rate on blends?",
];

export function Thread() {
  const stream = useStreamContext();
  const [threadId] = useQueryState("threadId");
  const [input, setInput] = useState("");

  const messages = stream.messages.filter((m) => !m.id?.startsWith("do-not-render-"));
  const interrupt = stream.interrupt?.value as MarketingInterrupt | undefined;
  const isLoading = stream.isLoading;
  const isEmpty = messages.length === 0 && !isLoading;

  // The last turn is human (or empty) → the model hasn't started replying yet → show the dots.
  const lastIsHuman = messages.length > 0 && messages[messages.length - 1].type === "human";
  const briefsHref = threadId ? `/briefs?threadId=${threadId}` : "/briefs";

  const send = (text: string) => {
    const content = text.trim();
    if (!content) return;
    setInput("");
    stream.submit(
      { messages: [{ type: "human", content }] },
      {
        streamMode: ["values"],
        // Stream the analytics agent subgraph's messages too — its run_sql steps and the final
        // answer flow in live (the subgraph is a real node in the orchestrator graph).
        streamSubgraphs: true,
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

  return (
    <AppShell
      title="Ask Nora"
      subtitle="Analytics agent + marketing workflow"
      hideAsk
    >
      <AskNoraModeLane />
      <MessageList
        messages={messages}
        isLoading={isLoading}
        lastIsHuman={lastIsHuman}
        interrupt={interrupt}
        isEmpty={isEmpty}
        briefsHref={briefsHref}
        onPick={send}
      />

      <footer className="shrink-0 border-t bg-background">
        <form
          className="mx-auto flex max-w-3xl items-center gap-2.5 px-[26px] py-4"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about the business, or ask for a video ad…"
            className="h-12 rounded-[11px] text-[13.5px]"
          />
          {isLoading ? (
            <Button
              type="button"
              size="icon"
              variant="outline"
              onClick={() => stream.stop()}
              className="size-12 shrink-0 rounded-[11px]"
              aria-label="Stop"
            >
              <Square className="size-4" />
            </Button>
          ) : (
            <Button
              type="submit"
              size="icon"
              disabled={!input.trim()}
              className="size-12 shrink-0 rounded-[11px]"
              aria-label="Send message"
            >
              <ArrowUp className="size-5" />
            </Button>
          )}
        </form>
      </footer>
    </AppShell>
  );
}

function MessageList({
  messages,
  isLoading,
  lastIsHuman,
  interrupt,
  isEmpty,
  briefsHref,
  onPick,
}: {
  messages: Message[];
  isLoading: boolean;
  lastIsHuman: boolean;
  interrupt: MarketingInterrupt | undefined;
  isEmpty: boolean;
  briefsHref: string;
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

  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      className="relative min-h-0 flex-1 overflow-y-auto bg-body-bg"
    >
      <div className="mx-auto max-w-3xl px-[26px] py-6">
        {isEmpty ? (
          <EmptyState onPick={onPick} />
        ) : (
          <div className="flex flex-col gap-[18px]">
            {messages.map((message, idx) => {
              const prev = messages[idx - 1];
              // Group consecutive assistant-side rows (the agent's tool steps + final answer) under
              // one Nora block: a row "continues" the turn when the previous message was AI or tool.
              const continuation = !!prev && (prev.type === "ai" || prev.type === "tool");
              if (message.type === "human") {
                return (
                  <HumanMessage key={message.id ?? idx} message={message} isLoading={isLoading} />
                );
              }
              if (message.type === "ai") {
                return (
                  <AssistantMessage
                    key={message.id ?? idx}
                    message={message}
                    isLoading={isLoading}
                    continuation={continuation}
                  />
                );
              }
              // Tool result messages aren't rendered loose — each is paired into its tool call's
              // collapsible card (ToolStep) inside the AssistantMessage above.
              return null;
            })}

            {/* Two HITL gates. The concept-pick gate is an inline interactive selection (resumes
                right here); the script-review gate hands off to the dedicated /briefs surface. */}
            {interrupt &&
              (interrupt.kind === "concept_pick" ? (
                <ConceptPicker interrupt={interrupt} />
              ) : (
                <MarketingProgressCard briefsHref={briefsHref} />
              ))}

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

// The marketing workflow paused for review — a compact progress card that hands off to /briefs.
function MarketingProgressCard({ briefsHref }: { briefsHref: string }) {
  return (
    <div className="flex items-start gap-3">
      <NoraAvatar />
      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold">Nora</span>
          <span className="rounded-full border border-brand-edge bg-brand-tint px-2 py-px text-[9.5px] font-semibold text-brand-text">
            Marketing workflow
          </span>
        </div>
        <div className="rounded-[5px_13px_13px_13px] border border-brand-edge bg-brand-tint/30 px-[15px] py-3.5">
          <div className="mb-2.5 text-[12.5px] text-muted-foreground">
            Concept → script → <b className="text-brand-text">your review</b> → storyboard → prompts
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-brand-edge/50">
            <div className="h-full w-[52%] bg-brand" />
          </div>
          <div className="mt-3 text-[13.5px] font-medium">
            Script is ready — paused for your approval before I spend compute on the storyboard.
          </div>
          <Link
            href={briefsHref}
            className="mt-2.5 inline-block rounded-[8px] bg-ink px-[15px] py-2 text-[12.5px] font-medium text-ink-foreground"
          >
            Open review →
          </Link>
        </div>
      </div>
    </div>
  );
}

function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="flex flex-col items-center gap-6 py-16 text-center">
      <div className="flex size-14 items-center justify-center rounded-2xl bg-ink font-mono text-2xl font-semibold text-ink-foreground">
        N
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
