"use client";

import { useEffect, useRef, useState } from "react";
import { useStream } from "@langchain/langgraph-sdk/react";
import {
  uiMessageReducer,
  type RemoveUIMessage,
  type UIMessage,
} from "@langchain/langgraph-sdk/react-ui";
import type { Message } from "@langchain/langgraph-sdk";
import { useQueryState } from "nuqs";
import { ArrowUp, Sparkles, Square } from "lucide-react";
import { toast } from "sonner";

import { A2uiSurfaceView } from "@/components/A2uiSurfaceView";
import { AppShell } from "@/components/app-shell";
import { NoraAvatar } from "@/components/thread/messages/ai";
import { MarkdownText } from "@/components/thread/markdown";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { API_URL, STUDIO_ASSISTANT_ID } from "@/lib/config";
import { tagThread } from "@/lib/threads";
import type { A2uiBlock, NoraState, NoraUpdate } from "@/lib/types";
import { getContentString } from "@/lib/utils";
import { useThreads } from "@/providers/Thread";

const SUGGESTIONS = [
  "Revenue by product category last quarter",
  "Top 5 customers by total spend",
  "Monthly order volume this year",
];

// The A2UI dynamic-schema showcase: a self-contained surface on the `nora_a2ui` graph. Unlike
// /ask (the hoisted `nora` stream + the fixed AnalyticsDashboard), here a UI-author model COMPOSES
// the surface per answer — the "LLM authors the UI" pattern — delivered over the same native
// push_ui_message channel. Its own ephemeral stream keeps it isolated from the hoisted one.
export default function StudioPage() {
  // Persist the studio thread in the URL (its own `t` key, separate from the hoisted `nora`
  // provider's `threadId`) so a reload restores the conversation + its authored surfaces.
  const [threadId, setThreadId] = useQueryState("t");
  const [input, setInput] = useState("");
  const { getThreads, setThreads } = useThreads();

  const stream = useStream<
    NoraState,
    { UpdateType: NoraUpdate; CustomEventType: UIMessage | RemoveUIMessage }
  >({
    apiUrl: API_URL,
    assistantId: STUDIO_ASSISTANT_ID,
    threadId: threadId ?? null,
    messagesKey: "messages",
    fetchStateHistory: true,
    onThreadId: (id) => void setThreadId(id),
    onError: (err) =>
      toast.error("Something went wrong", {
        description: err instanceof Error ? err.message : String(err),
      }),
    onCustomEvent: (event, options) => {
      options.mutate((prev) => ({ ...prev, ui: uiMessageReducer(prev.ui ?? [], event) }));
    },
  });

  // Tag the thread (graph_id=studio + a title from the first message) once a run has settled, then
  // refresh the sidebar so it shows up in Recent — titled, routed back to /studio. Running after
  // the turn (not on creation) also retroactively titles older untitled studio threads on open.
  const tagged = useRef<string | null>(null);
  useEffect(() => {
    if (!threadId || stream.isLoading || tagged.current === threadId) return;
    if (!stream.messages.some((m) => m.type === "human")) return;
    tagged.current = threadId;
    tagThread(threadId, STUDIO_ASSISTANT_ID)
      .then(() => getThreads())
      .then(setThreads)
      .catch(console.error);
  }, [threadId, stream.isLoading, stream.messages, getThreads, setThreads]);

  const surfacesFor = (id?: string) =>
    (stream.values.ui ?? []).filter(
      (ui) =>
        ui.name === "a2ui_surface" &&
        (ui.metadata as { message_id?: string } | undefined)?.message_id === id,
    );

  // Render human turns, and AI turns that actually say something — an authored surface or text.
  // The analytics agent's tool-call steps (empty content, no surface) are dropped so the studio
  // shows the answer + the UI it authored, not blank "Nora" rows.
  const messages = stream.messages.filter(
    (m) =>
      m.type === "human" ||
      (m.type === "ai" && (!!getContentString(m.content) || surfacesFor(m.id).length > 0)),
  );
  const isLoading = stream.isLoading;
  const lastIsHuman = messages.length > 0 && messages[messages.length - 1].type === "human";

  const send = (text: string) => {
    const content = text.trim();
    if (!content) return;
    setInput("");
    stream.submit(
      { messages: [{ type: "human", content }] },
      {
        streamMode: ["values"],
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
    <AppShell title="Studio" subtitle="A2UI · the model authors the UI" hideAsk>
      <div className="min-h-0 flex-1 overflow-y-auto bg-body-bg">
        <div className="mx-auto max-w-3xl px-[26px] py-6">
          {messages.length === 0 && !isLoading ? (
            <EmptyState onPick={send} />
          ) : (
            <div className="flex flex-col gap-[18px]">
              {messages.map((m, i) =>
                m.type === "human" ? (
                  <HumanBubble key={m.id ?? i} text={getContentString(m.content)} />
                ) : (
                  <AgentTurn
                    key={m.id ?? i}
                    text={getContentString(m.content)}
                    surfaces={surfacesFor(m.id)}
                  />
                ),
              )}
              {isLoading && lastIsHuman && <Thinking />}
            </div>
          )}
        </div>
      </div>

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
            placeholder="Ask a business question — Nora authors a UI for the answer…"
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

function HumanBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] rounded-[13px_5px_13px_13px] bg-ink px-[15px] py-[10px] text-[13.5px] leading-[1.5] text-ink-foreground">
        {text}
      </div>
    </div>
  );
}

function AgentTurn({
  text,
  surfaces,
}: {
  text: string;
  surfaces: { id: string; props: Record<string, unknown> }[];
}) {
  return (
    <div className="flex items-start gap-3">
      <NoraAvatar />
      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold">Nora</span>
          <span className="flex items-center gap-1 rounded-full bg-ink px-2 py-px text-[9.5px] font-semibold text-ink-foreground">
            <Sparkles className="size-2.5" /> A2UI
          </span>
        </div>
        {text && (
          <div className="rounded-[5px_13px_13px_13px] border bg-card px-[15px] py-[13px] text-[13.5px] leading-[1.55]">
            <MarkdownText>{text}</MarkdownText>
          </div>
        )}
        {surfaces.map((ui) => (
          <A2uiSurfaceView key={ui.id} blocks={(ui.props.blocks as A2uiBlock[]) ?? []} />
        ))}
      </div>
    </div>
  );
}

function Thinking() {
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

function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="flex flex-col items-center gap-6 py-16 text-center">
      <div className="flex size-14 items-center justify-center rounded-2xl bg-ink text-ink-foreground">
        <Sparkles className="size-6" />
      </div>
      <div className="space-y-1.5">
        <h2 className="text-xl font-semibold">The model authors the UI</h2>
        <p className="mx-auto max-w-md text-sm text-muted-foreground">
          Ask a business question. The analytics agent answers, then a second model{" "}
          <b>composes</b> a UI — headings, KPIs, the right chart, a table — to fit the data
          (dynamic-schema A2UI).
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
