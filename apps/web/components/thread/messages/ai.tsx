"use client";

import { useState, type ComponentProps } from "react";
import { ChefHat, Check, Copy, RefreshCw } from "lucide-react";
import type { Message } from "@langchain/langgraph-sdk";

import { LoadExternalComponent } from "@langchain/langgraph-sdk/react-ui";

import { AnalyticsDashboard } from "@/components/AnalyticsDashboard";
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

// A blank avatar-width spacer, so continuation rows (the agent's tool steps) align under the one
// Nora avatar at the top of the turn instead of each getting their own.
function AvatarSpacer() {
  return <div className="size-8 shrink-0" />;
}

export function AssistantMessage({
  message,
  isLoading,
  continuation = false,
}: {
  message: Message;
  isLoading: boolean;
  // True when the previous message was also assistant-side (an AI/tool step), so this row joins
  // the same Nora block (no repeated avatar/header) — the agent's work reads as one turn.
  continuation?: boolean;
}) {
  const stream = useStreamContext();
  const meta = stream.getMessagesMetadata(message);
  const parentCheckpoint = meta?.firstSeenState?.parent_checkpoint;

  const text = getContentString(message.content);
  const { video_brief: brief } = getNoraKwargs(message);
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
    stream.submit(undefined, {
      checkpoint: parentCheckpoint,
      streamMode: ["values"],
      streamSubgraphs: true,
    });
  };

  return (
    <div className="group flex items-start gap-3">
      {continuation ? <AvatarSpacer /> : <NoraAvatar />}
      <div className="min-w-0 flex-1 space-y-2">
        {!continuation && (
          <div className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Nora
          </div>
        )}

        {text && <MarkdownText>{text}</MarkdownText>}

        {toolCalls.map((tc, i) => (
          <ToolCall key={i} name={tc.name} args={tc.args} />
        ))}

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

        {/* Actions sit on the message that carries the final text answer, not the tool steps. */}
        {text && (
          <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
            <BranchSwitcher
              branch={meta?.branch}
              branchOptions={meta?.branchOptions}
              onSelect={(b) => stream.setBranch(b)}
              disabled={isLoading}
            />
            <button
              type="button"
              title="Copy"
              aria-label="Copy message"
              onClick={copy}
              className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            </button>
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
        )}
      </div>
    </div>
  );
}

// A run_sql / describe_table call the agent made, streamed live. For run_sql we surface the SQL
// itself (the interesting bit); other tools show their raw args.
function ToolCall({ name, args }: { name: string; args: Record<string, unknown> }) {
  const query = name === "run_sql" ? (args.query as string | undefined) : undefined;
  return (
    <div className="rounded-lg border bg-muted/40 px-2.5 py-1.5 font-mono text-xs text-muted-foreground">
      <div className="flex items-center gap-1.5">
        <span className="text-muted-foreground/70">▸</span>
        <span className="font-medium">{name}</span>
        {!query && <span className="truncate">({JSON.stringify(args)})</span>}
      </div>
      {query && (
        <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-words text-foreground/80">
          {query}
        </pre>
      )}
    </div>
  );
}

// The result of a tool call (a ToolMessage) — query rows, a table schema, or a SQL error the
// agent then repairs. Rendered compactly, aligned under the same Nora block.
export function ToolResultMessage({ message }: { message: Message }) {
  const result = getContentString(message.content);
  const name = (message as { name?: string }).name ?? "result";
  return (
    <div className="flex items-start gap-3">
      <AvatarSpacer />
      <div className="min-w-0 flex-1">
        <div className="rounded-lg border bg-muted/20 px-2.5 py-1.5 font-mono text-xs text-muted-foreground">
          <div className="mb-1 font-medium">{name} → result</div>
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words text-foreground/70">
            {result}
          </pre>
        </div>
      </div>
    </div>
  );
}
