"use client";

import { Fragment, useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { useQueryState } from "nuqs";
import { useSession } from "next-auth/react";
import { ArrowDown, ArrowUp, Sparkles, Square } from "lucide-react";
import type { Message } from "@langchain/langgraph-sdk";

import { AppShell } from "@/components/app-shell";
import { ConceptPicker } from "@/components/ConceptPicker";
import { WorkspaceApproval } from "@/components/workspace/workspace-approval";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { isWorkspaceApproval } from "@/lib/types";
import type { ThreadInterrupt } from "@/lib/types";
import { AUTH_REQUIRED, WORKSPACE_ENABLED } from "@/lib/config";
import { cn } from "@/lib/utils";
import { buildSubmitConfig, AUTHOR_UI_KEY } from "@/lib/run-config";
import { useStreamContext } from "@/providers/Stream";
import { SignInGate } from "@/components/auth/sign-in-gate";
import { WorkspaceConnect } from "@/components/workspace/workspace-connect";
import { AskNoraModeLane } from "./AskNoraModeLane";
import { AssistantTurn, NoraAvatar } from "./messages/ai";
import { HumanMessage } from "./messages/human";

const SUGGESTIONS = [
  "What was our best-selling product in Colombo last quarter?",
  "Make a 30s video ad for it",
  "What's the refund rate on blends?",
  ...(WORKSPACE_ENABLED
    ? ["Email priya@example.com that the cloves shipment is delayed two days"]
    : []),
];

// A boolean preference persisted to localStorage, read via useSyncExternalStore so it's SSR-safe and
// has no setState-in-effect. getServerSnapshot returns `defaultValue`, which React also uses for the
// first client render, so hydration matches; React then re-reads the real value post-hydration. The
// snapshot is a primitive boolean (Object.is-stable), so there's no render loop. The setter writes
// through and dispatches a synthetic `storage` event so the current tab re-reads (the native event
// only fires in OTHER tabs); listening to real `storage` events keeps tabs in sync too.
function useLocalStorageBoolean(key: string, defaultValue: boolean) {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const handler = (e: StorageEvent) => {
        if (e.key === null || e.key === key) onChange();
      };
      window.addEventListener("storage", handler);
      return () => window.removeEventListener("storage", handler);
    },
    [key],
  );
  const getSnapshot = useCallback(() => {
    try {
      return window.localStorage.getItem(key) === "true";
    } catch {
      return defaultValue;
    }
  }, [key, defaultValue]);
  const value = useSyncExternalStore(subscribe, getSnapshot, () => defaultValue);
  const set = useCallback(
    (next: boolean) => {
      try {
        window.localStorage.setItem(key, String(next));
      } catch {
        /* localStorage unavailable (private mode / SSR) — ignore */
      }
      window.dispatchEvent(new StorageEvent("storage", { key }));
    },
    [key],
  );
  return [value, set] as const;
}

export function Thread() {
  const stream = useStreamContext();
  const [threadId] = useQueryState("threadId");
  // "Author UI" output mode — a GLOBAL, persisted preference (not a URL param), so it survives
  // navigating between threads instead of silently resetting. It's an on-demand per-run rendering
  // choice: when on, each message you send asks the analytics path to COMPOSE a custom UI surface
  // (config.configurable.ui_mode="authored") instead of the fixed dashboard, until you turn it off.
  const [authorUi, setAuthorUi] = useLocalStorageBoolean(AUTHOR_UI_KEY, false);
  const [input, setInput] = useState("");
  const { status } = useSession();

  const messages = stream.messages.filter((m) => !m.id?.startsWith("do-not-render-"));
  const interrupt = stream.interrupt?.value as ThreadInterrupt | undefined;
  const isLoading = stream.isLoading;
  const isEmpty = messages.length === 0 && !isLoading;

  // The last turn is human (or empty) → the model hasn't started replying yet → show the dots.
  const lastIsHuman = messages.length > 0 && messages[messages.length - 1].type === "human";
  const briefsHref = threadId ? `/briefs?threadId=${threadId}` : "/briefs";

  const send = async (text: string) => {
    const content = text.trim();
    if (!content) return;
    setInput("");
    // The per-run config (Google token + Author-UI mode) is built by the shared seam so this path
    // and edit / regenerate / HITL-resume all attach it identically — see lib/run-config.ts.
    // NOTE (tracing): the Langfuse Sessions view already groups this thread's turns by thread_id
    // automatically (Aegra's OTEL instrumentation sets the session). Per-turn trace *naming* /tags
    // can't be set from here — the SDK's submit `config` only carries `configurable`, and the trace
    // attributes are owned by Aegra's OTEL layer. The CLI path (app.py) names turns by message.
    const runConfig = await buildSubmitConfig();
    stream.submit(
      { messages: [{ type: "human", content }] },
      {
        streamMode: ["values"],
        // Stream the analytics agent subgraph's messages too — its run_sql steps and the final
        // answer flow in live (the subgraph is a real node in the orchestrator graph).
        streamSubgraphs: true,
        ...runConfig,
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

  // Custom-auth mode: Nora's threads are per-operator, so require sign-in before the chat.
  if (AUTH_REQUIRED && status !== "authenticated") {
    return (
      <AppShell title="Ask Nora" subtitle="Sign in to continue" hideAsk>
        <SignInGate loading={status === "loading"} />
      </AppShell>
    );
  }

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
        <WorkspaceConnect />
        <div className="mx-auto flex max-w-3xl items-center justify-end px-[26px] pt-3">
          {/* Output-mode toggle: an on-demand, persisted preference. When on, each answer comes back
              as an LLM-authored A2UI surface instead of the fixed dashboard (sets ui_mode="authored"
              on the run), and it stays on across threads until you turn it off. */}
          <button
            type="button"
            onClick={() => setAuthorUi(!authorUi)}
            aria-pressed={authorUi}
            title="Compose a custom UI for your next answer (applies until you turn it off)"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[11px] font-semibold transition-colors",
              authorUi
                ? "border-brand-edge bg-brand-tint text-brand-text"
                : "border-border bg-card text-muted-foreground hover:text-foreground",
            )}
          >
            <Sparkles className="size-3.5" />
            Author UI
          </button>
        </div>
        <form
          className="mx-auto flex max-w-3xl items-center gap-2.5 px-[26px] pt-2.5 pb-4"
          onSubmit={(e) => {
            e.preventDefault();
            void send(input);
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

// A conversational turn: a human message followed by the assistant-side run it produced (the AI
// messages — supervisor handoffs + each delegated subagent's work). Tool messages are excluded here
// (they're paired into their tool-step cards downstream), but remain in stream.messages.
type Turn = { key: string; human?: Message; ai: Message[] };

// Group the flat message list into turns: a human message starts a turn and collects every AI
// message until the next human. An assistant-led run with no preceding human (only at the very
// start) still forms a turn so nothing is dropped.
function groupTurns(messages: Message[]): Turn[] {
  const turns: Turn[] = [];
  let current: Turn | null = null;
  messages.forEach((m, i) => {
    if (m.type === "human") {
      if (current) turns.push(current);
      current = { key: m.id ?? `turn-${i}`, human: m, ai: [] };
    } else if (m.type === "ai") {
      if (!current) current = { key: m.id ?? `turn-${i}`, ai: [] };
      current.ai.push(m);
    }
    // tool messages: skipped here — rendered inside their tool-step card, not as a turn member.
  });
  if (current) turns.push(current);
  return turns;
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
  interrupt: ThreadInterrupt | undefined;
  isEmpty: boolean;
  briefsHref: string;
  onPick: (text: string) => void;
}) {
  const turns = groupTurns(messages);
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

  // Follow new content (tokens + new messages) only when the user is already at the bottom. This
  // path only scrolls the DOM — it sets no state (we're already at the bottom, so the scroll button
  // stays hidden via onScroll), which keeps the prop-driven effect free of state adjustments.
  useEffect(() => {
    if (atBottomRef.current) endRef.current?.scrollIntoView({ behavior: "smooth" });
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
            {/* Group the flat stream into turns (a human message + the assistant-side run it
                produced), then render the human bubble and ONE AssistantTurn per turn. AssistantTurn
                segments its messages into supervisor→subagent delegation boundaries + lanes. Tool
                messages are dropped from the turn here but stay in stream.messages, so each is still
                paired into its tool-step card via the resultFor lookup inside the lane. */}
            {turns.map((turn, idx) => (
              <Fragment key={turn.key}>
                {turn.human && (
                  <HumanMessage message={turn.human} isLoading={isLoading} />
                )}
                {turn.ai.length > 0 && (
                  <AssistantTurn
                    messages={turn.ai}
                    isLoading={isLoading}
                    isActive={isLoading && idx === turns.length - 1}
                  />
                )}
              </Fragment>
            ))}

            {/* Two HITL gates. The concept-pick gate is an inline interactive selection (resumes
                right here); the script-review gate hands off to the dedicated /briefs surface. */}
            {interrupt &&
              (isWorkspaceApproval(interrupt) ? (
                <WorkspaceApproval interrupt={interrupt} />
              ) : interrupt.kind === "concept_pick" ? (
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
            className="size-1.5 animate-pulse rounded-full bg-muted-foreground/60"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </div>
    </div>
  );
}
