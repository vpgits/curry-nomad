"use client";

import { useState, type ComponentProps } from "react";
import { ChefHat, Check, Copy, RefreshCw, Wrench } from "lucide-react";
import type { Message } from "@langchain/langgraph-sdk";

import { LoadExternalComponent } from "@langchain/langgraph-sdk/react-ui";

import { AnalyticsDashboard } from "@/components/AnalyticsDashboard";
import { SqlTraceCard } from "@/components/SqlTraceCard";
import { VideoBriefCard } from "@/components/VideoBriefCard";
import { cn, getContentString, getNoraKwargs } from "@/lib/utils";
import { useStreamContext } from "@/providers/Stream";
import { MarkdownText } from "../markdown";
import { BranchSwitcher } from "./shared";

// Client-side component map for push_ui_message UI messages — LoadExternalComponent renders these
// directly (no remote bundle fetch, which the local dev server can't serve anyway).
const UI_COMPONENTS = { analytics_dashboard: AnalyticsDashboard };

export function NoraAvatar() {
  return (
    <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
      <ChefHat className="size-4" />
    </div>
  );
}

export function AssistantMessage({
  message,
  isLoading,
}: {
  message: Message;
  isLoading: boolean;
}) {
  const stream = useStreamContext();
  const meta = stream.getMessagesMetadata(message);
  const parentCheckpoint = meta?.firstSeenState?.parent_checkpoint;

  const text = getContentString(message.content);
  const { tool_trace: toolTrace, video_brief: brief } = getNoraKwargs(message);
  const toolCalls =
    (message as { tool_calls?: { name: string; args: Record<string, unknown> }[] }).tool_calls ??
    [];
  // push_ui_message UI messages tagged to this AI message (the generative-UI dashboard).
  const uiForMessage = (stream.values.ui ?? []).filter(
    (ui) => (ui.metadata as { message_id?: string } | undefined)?.message_id === message.id,
  );

  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  const regenerate = () => {
    stream.submit(undefined, { checkpoint: parentCheckpoint, streamMode: ["values"] });
  };

  return (
    <div className="group flex items-start gap-3">
      <NoraAvatar />
      <div className="min-w-0 flex-1 space-y-2">
        <div className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
          Nora
        </div>

        {text && <MarkdownText>{text}</MarkdownText>}

        {toolCalls.map((tc, i) => (
          <ToolCall key={i} name={tc.name} args={tc.args} />
        ))}

        {toolTrace && toolTrace.length > 0 && <SqlTraceCard trace={toolTrace} />}

        {brief && <VideoBriefCard brief={brief} />}

        {uiForMessage.map((ui) => (
          <LoadExternalComponent
            key={ui.id}
            // Cast at the boundary: LoadExternalComponent's prop types are deliberately loose
            // (Record<string, unknown> state, {}-prop components); our typed stream + dashboard
            // component are stricter. Runtime behaviour is correct (ui.props → AnalyticsDashboard).
            stream={stream as ComponentProps<typeof LoadExternalComponent>["stream"]}
            message={ui}
            components={
              UI_COMPONENTS as unknown as ComponentProps<typeof LoadExternalComponent>["components"]
            }
          />
        ))}

        <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
          <BranchSwitcher
            branch={meta?.branch}
            branchOptions={meta?.branchOptions}
            onSelect={(b) => stream.setBranch(b)}
            disabled={isLoading}
          />
          {text && (
            <button
              type="button"
              title="Copy"
              aria-label="Copy message"
              onClick={copy}
              className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            </button>
          )}
          <button
            type="button"
            title="Regenerate"
            aria-label="Regenerate response"
            disabled={isLoading}
            onClick={regenerate}
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
          >
            <RefreshCw className="size-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
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
