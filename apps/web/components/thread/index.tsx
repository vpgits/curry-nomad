"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import { useQueryState } from "nuqs";
import { useSession } from "next-auth/react";
import { ArrowDown, ArrowUp, Square } from "lucide-react";
import type { Message } from "@langchain/langgraph-sdk";

import { AppShell } from "@/components/app-shell";
import { ConceptPicker } from "@/components/ConceptPicker";
import { CopyReview } from "@/components/CopyReview";
import { StillReview } from "@/components/StillReview";
import { WorkspaceApproval } from "@/components/workspace/workspace-approval";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { isWorkspaceApproval } from "@/lib/types";
import type { ThreadInterrupt } from "@/lib/types";
import { AUTH_REQUIRED, WORKSPACE_ENABLED } from "@/lib/config";
import { buildSubmitConfig } from "@/lib/run-config";
import { useStreamContext } from "@/providers/Stream";
import { SignInGate } from "@/components/auth/sign-in-gate";
import { WorkspaceConnect } from "@/components/workspace/workspace-connect";
import { CardErrorBoundary } from "./card-error-boundary";
import { useHitlSteps } from "@/lib/hitl-log";
import { ResolvedSteps } from "./ResolvedSteps";
import { AssistantTurn, NoraAvatar } from "./messages/ai";
import { HumanMessage } from "./messages/human";

const SUGGESTIONS = [
  "What was our best-selling product in Colombo last quarter?",
  "Make an Instagram post for it",
  "What's the refund rate on blends?",
  ...(WORKSPACE_ENABLED
    ? ["Email priya@example.com that the cloves shipment is delayed two days"]
    : []),
];

export function Thread() {
  const stream = useStreamContext();
  const [threadId] = useQueryState("threadId");
  const [input, setInput] = useState("");
  const { status } = useSession();

  const messages = stream.messages.filter((m) => !m.id?.startsWith("do-not-render-"));
  const interrupt = stream.interrupt?.value as ThreadInterrupt | undefined;
  const isLoading = stream.isLoading;
  const isEmpty = messages.length === 0 && !isLoading;

  // The last turn is human (or empty) → the model hasn't started replying yet → show the dots.
  const lastIsHuman = messages.length > 0 && messages[messages.length - 1].type === "human";

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
    <AppShell title="Ask Nora" hideAsk>
      <MessageList
        messages={messages}
        isLoading={isLoading}
        lastIsHuman={lastIsHuman}
        interrupt={interrupt}
        isEmpty={isEmpty}
        threadId={threadId}
        onPick={send}
      />

      <footer className="shrink-0 border-t bg-background">
        <WorkspaceConnect />
        <form
          className="mx-auto flex max-w-7xl items-center gap-2.5 px-[26px] pt-2 pb-3.5"
          onSubmit={(e) => {
            e.preventDefault();
            void send(input);
          }}
        >
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about the business, or ask for an Instagram post…"
            className="h-11 rounded-[11px] text-[13.5px]"
          />
          {isLoading ? (
            <Button
              type="button"
              size="icon"
              variant="outline"
              onClick={() => stream.stop()}
              className="size-11 shrink-0 rounded-[11px]"
              aria-label="Stop"
            >
              <Square className="size-4" />
            </Button>
          ) : (
            <Button
              type="submit"
              size="icon"
              disabled={!input.trim()}
              className="size-11 shrink-0 rounded-[11px]"
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
  threadId,
  onPick,
}: {
  messages: Message[];
  isLoading: boolean;
  lastIsHuman: boolean;
  interrupt: ThreadInterrupt | undefined;
  isEmpty: boolean;
  threadId: string | null;
  onPick: (text: string) => void;
}) {
  const turns = groupTurns(messages);
  // Resolved-HITL records for this thread, rendered INLINE after the turn each one is anchored to.
  const hitlSteps = useHitlSteps(threadId);
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
      <div className="mx-auto max-w-7xl px-[26px] py-5">
        {isEmpty ? (
          <EmptyState onPick={onPick} />
        ) : (
          <div className="flex flex-col gap-[18px]">
            {/* Group the flat stream into turns (a human message + the assistant-side run it
                produced), then render the human bubble and ONE AssistantTurn per turn. AssistantTurn
                segments its messages into supervisor→subagent delegation boundaries + lanes. Tool
                messages are dropped from the turn here but stay in stream.messages, so each is still
                paired into its tool-step card via the resultFor lookup inside the lane. */}
            {turns.map((turn, idx) => {
              // Resolved HITL records anchored to a message in THIS turn — rendered inline, in order,
              // right where the gate was. Records with no anchor (pre-anchoring cruft) don't show.
              const turnSteps = hitlSteps.filter(
                (st) =>
                  st.anchorId != null &&
                  (st.anchorId === turn.human?.id || turn.ai.some((m) => m.id === st.anchorId)),
              );
              return (
                <Fragment key={turn.key}>
                  {turn.human && <HumanMessage message={turn.human} isLoading={isLoading} />}
                  {turn.ai.length > 0 && (
                    // Per-turn boundary: a render error in one assistant turn (outside a gen-UI card)
                    // degrades to an inline notice instead of blanking the whole /ask screen.
                    <CardErrorBoundary label="this response" resetKeys={[turn.ai.length, isLoading]}>
                      <AssistantTurn
                        messages={turn.ai}
                        isLoading={isLoading}
                        isActive={isLoading && idx === turns.length - 1}
                      />
                    </CardErrorBoundary>
                  )}
                  {/* Resolved HITL decisions for this turn (gates are transient and leave no message),
                      inline and in order — concept pick, copy/still review, workspace approvals. */}
                  {turnSteps.length > 0 && <ResolvedSteps steps={turnSteps} />}
                </Fragment>
              );
            })}

            {/* HITL gates, all inline in the conversation: concept pick, copy review (caption + post
                settings), still review, and workspace write-approval. Each resumes the paused run in
                place. */}
            {interrupt && (
              <CardErrorBoundary
                label={`interrupt:${interrupt.kind ?? "?"}`}
                resetKeys={[interrupt.kind ?? null, turns.length, isLoading]}
              >
                {isWorkspaceApproval(interrupt) ? (
                  <WorkspaceApproval interrupt={interrupt} />
                ) : interrupt.kind === "still_review" ? (
                  <StillReview interrupt={interrupt} />
                ) : interrupt.kind === "concept_pick" ? (
                  <ConceptPicker interrupt={interrupt} />
                ) : (
                  <CopyReview key={interrupt.caption} interrupt={interrupt} />
                )}
              </CardErrorBoundary>
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
      <div className="flex size-14 items-center justify-center rounded-2xl bg-ink font-mono text-2xl font-semibold text-ink-foreground">
        N
      </div>
      <div className="space-y-1.5">
        <h2 className="text-xl font-semibold">How can Nora help?</h2>
        <p className="mx-auto max-w-md text-sm text-muted-foreground">
          Ask about the business and the analytics <b>agent</b> answers; ask for an Instagram post
          and the marketing <b>workflow</b> builds one — with a human-review gate.
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
