"use client";

import { useState, type ComponentProps, type ReactNode } from "react";
import { ChefHat, Check, ChevronRight, Copy, Database, RefreshCw, Table2 } from "lucide-react";
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

type ToolCall = { name: string; args: Record<string, unknown>; id?: string };

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
  const toolCalls = (message as { tool_calls?: ToolCall[] }).tool_calls ?? [];
  // Pair each tool call with its result ToolMessage (matched by id) so a call + its result render
  // as one collapsible card — the ToolMessages themselves are consumed here, not rendered loose.
  const resultFor = (id?: string) =>
    id
      ? stream.messages.find((m) => (m as { tool_call_id?: string }).tool_call_id === id)
      : undefined;

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

        {toolCalls.length > 0 && (
          // One AI message's tool calls = one step. Calls in the same message ran in PARALLEL
          // (ToolNode fires them together); a later message is a SEQUENTIAL step. Thread them.
          <ToolStepGroup calls={toolCalls} resultFor={resultFor} continuation={continuation} />
        )}

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

// One STEP of the agent's work, drawn on a thread rail. The calls in this step ran in parallel
// (they branch off a fork node); a `continuation` step had a prior step, so the rail extends up to
// connect to it (sequential). This is the parallel-vs-sequential "threading".
function ToolStepGroup({
  calls,
  resultFor,
  continuation,
}: {
  calls: ToolCall[];
  resultFor: (id?: string) => Message | undefined;
  continuation: boolean;
}) {
  const parallel = calls.length > 1;
  const label = parallel
    ? `ran ${calls.length} in parallel`
    : continuation
      ? "then"
      : "ran 1 call";
  return (
    <div className="relative pl-5">
      {/* the thread rail — extends upward into the gap for continuation steps so the rail of the
          previous step connects to this one (sequential), giving a continuous timeline. */}
      <div
        className={cn(
          "absolute left-2 w-px -translate-x-1/2 bg-border",
          continuation ? "-top-6 bottom-2" : "top-1.5 bottom-2",
        )}
      />
      {/* fork node sits ON the rail (absolute to the container, centred on the rail's x); the label
          flows to its right at pl-5, so the dot never lands on the text. */}
      <span className="absolute top-2 left-2 size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-muted-foreground/60" />
      <div className="mb-1.5 text-[11px] font-medium text-muted-foreground">{label}</div>
      {/* the calls — branches off the fork (each connected to the rail by a short tick) */}
      <div className="space-y-1.5">
        {calls.map((c, i) => (
          <div key={c.id ?? i} className="relative">
            <span className="absolute top-[13px] left-[-12px] h-px w-3 bg-border" />
            <ToolStep call={c} result={resultFor(c.id)} />
          </div>
        ))}
      </div>
    </div>
  );
}

// One step of the agent's work — a tool call paired with its result — as a thin collapsible card.
// Collapsed by default (so a turn is a tidy list of steps, not a wall of SQL + schema dumps); the
// header summarises it (run_sql → row count, describe_table → which table), and expanding reveals
// the SQL (lightly highlighted) + the result rendered as a table, or the raw result for other tools.
function ToolStep({ call, result }: { call: ToolCall; result?: Message }) {
  const [open, setOpen] = useState(false);
  const isSql = call.name === "run_sql";
  const query = isSql ? (call.args.query as string | undefined) : undefined;
  const resultText = result ? getContentString(result.content) : "";
  const running = !result;
  const parsed = isSql && resultText ? parseSqlResult(resultText) : null;

  const rowN = parsed ? (parsed.rowCount ?? parsed.rows.length) : 0;
  const summary = isSql
    ? running
      ? "running…"
      : parsed?.error
        ? "error — retrying"
        : parsed
          ? `${rowN} row${rowN === 1 ? "" : "s"}`
          : ""
    : typeof call.args.table === "string"
      ? call.args.table
      : running
        ? "running…"
        : "done";

  return (
    <div className="overflow-hidden rounded-lg border bg-muted/30 text-xs">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-left font-mono text-muted-foreground transition-colors hover:bg-muted/50"
      >
        <ChevronRight className={cn("size-3 shrink-0 transition-transform", open && "rotate-90")} />
        {isSql ? (
          <Table2 className="size-3 shrink-0 text-muted-foreground/70" />
        ) : (
          <Database className="size-3 shrink-0 text-muted-foreground/70" />
        )}
        <span className="font-medium text-foreground/80">{call.name}</span>
        {summary && <span className="truncate text-muted-foreground/80">· {summary}</span>}
        {running && (
          <span className="ml-auto flex shrink-0 items-center gap-1 text-muted-foreground/60">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="size-1 animate-bounce rounded-full bg-current"
                style={{ animationDelay: `${i * 0.15}s` }}
              />
            ))}
          </span>
        )}
      </button>

      {open && (
        <div className="space-y-2 border-t bg-background/40 px-2.5 py-2">
          {query ? (
            <SqlBlock sql={query} />
          ) : (
            !isSql && (
              <pre className="overflow-x-auto font-mono text-[11px] text-muted-foreground">
                {JSON.stringify(call.args)}
              </pre>
            )
          )}
          {result &&
            (parsed ? (
              <SqlResultView parsed={parsed} />
            ) : (
              <pre className="max-h-48 overflow-auto font-mono text-[11px] whitespace-pre-wrap break-words text-foreground/70">
                {resultText}
              </pre>
            ))}
        </div>
      )}
    </div>
  );
}

// SQL keywords get a subtle accent. A safe tokenizer (split on non-word runs, keep them) renders
// React spans — no dangerouslySetInnerHTML — so it can't break on quotes/identifiers.
const SQL_KEYWORDS = new Set(
  (
    "with select from where join left right inner outer full cross on group by order limit offset " +
    "as and or not in is null like between case when then else end union all distinct having " +
    "sum count avg min max coalesce nullif round cast strftime desc asc"
  )
    .toUpperCase()
    .split(" "),
);

function SqlBlock({ sql }: { sql: string }) {
  const tokens = sql.split(/([^A-Za-z_]+)/);
  return (
    <pre className="overflow-x-auto rounded-md bg-muted/40 p-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-words text-foreground/80">
      {tokens.map((tok, i): ReactNode =>
        SQL_KEYWORDS.has(tok.toUpperCase()) ? (
          <span key={i} className="font-semibold text-sky-400">
            {tok}
          </span>
        ) : (
          <span key={i}>{tok}</span>
        ),
      )}
    </pre>
  );
}

type ParsedSql = { columns: string[]; rows: string[][]; rowCount: number | null; error?: string };

// Parse the run_sql tool result string (see analytics/tools.py:_format_rows):
//   "col1 | col2\nval | val\n(N row(s))"   — or an error the agent will self-correct from.
function parseSqlResult(text: string): ParsedSql {
  const trimmed = text.trim();
  if (/^your query failed/i.test(trimmed)) {
    return { columns: [], rows: [], rowCount: null, error: trimmed };
  }
  const lines = trimmed.split("\n");
  const footer = lines[lines.length - 1]?.match(/^\((\d+) row(?:\(s\)|s)\)$/);
  const rowCount = footer ? parseInt(footer[1], 10) : null;
  const dataLines = footer ? lines.slice(0, -1) : lines;
  const [header, ...rest] = dataLines;
  const columns = header ? header.split(" | ") : [];
  const rows = rest.filter((r) => r.length > 0).map((r) => r.split(" | "));
  return { columns, rows, rowCount };
}

function SqlResultView({ parsed }: { parsed: ParsedSql }) {
  if (parsed.error) {
    return (
      <div className="rounded-md border border-destructive/30 bg-destructive/10 p-2 font-mono text-[11px] whitespace-pre-wrap text-destructive">
        {parsed.error}
      </div>
    );
  }
  if (parsed.columns.length === 0 || parsed.rows.length === 0) {
    return <div className="text-[11px] text-muted-foreground">No rows.</div>;
  }
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full border-collapse text-[11px]">
        <thead className="bg-muted/50">
          <tr>
            {parsed.columns.map((col, i) => (
              <th key={i} className="border-b px-2 py-1 text-left font-medium whitespace-nowrap">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {parsed.rows.map((row, r) => (
            <tr key={r}>
              {row.map((cell, c) => (
                <td key={c} className="border-b px-2 py-1 tabular-nums whitespace-nowrap">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
