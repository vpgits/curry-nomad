"use client";

import { useState, type ComponentProps, type ReactNode } from "react";
import {
  ArrowRight,
  Brain,
  Check,
  ChevronRight,
  Copy,
  CornerUpLeft,
  Database,
  RefreshCw,
  Table2,
} from "lucide-react";
import type { Message } from "@langchain/langgraph-sdk";

import { LoadExternalComponent } from "@langchain/langgraph-sdk/react-ui";
import { toast } from "sonner";

import { A2uiSurfaceView } from "@/components/A2uiSurfaceView";
import { AnalyticsDashboard } from "@/components/AnalyticsDashboard";
import { CritiqueCard } from "@/components/CritiqueCard";
import { MarketingRenderCard } from "@/components/MarketingRenderCard";
import { RouteMapCard } from "@/components/operations/RouteMapCard";
import { ScriptTimeline } from "@/components/ScriptTimeline";
import { StoryboardFilmstrip } from "@/components/StoryboardFilmstrip";
import { VideoBriefCard } from "@/components/VideoBriefCard";
import { WorkspaceActionsCard } from "@/components/workspace/workspace-actions-card";
import { cn, getContentString, getReasoningString } from "@/lib/utils";
import { buildSubmitConfig } from "@/lib/run-config";
import { useSubmitLock } from "@/lib/use-submit-lock";
import { useStreamContext } from "@/providers/Stream";
import { MarkdownText } from "../markdown";
import { CardErrorBoundary } from "../card-error-boundary";
import { BranchSwitcher } from "./shared";

// Client-side component map for push_ui_message UI messages — LoadExternalComponent renders these
// directly (no remote bundle fetch, which the local dev server can't serve anyway). Both the
// analytics path and the marketing path now push onto this one channel (the marketing brief used
// to ride additional_kwargs); each ui.name keys into this map.
const UI_COMPONENTS = {
  analytics_dashboard: AnalyticsDashboard,
  // The "Author UI" output mode: when the composer toggles ui_mode="authored", the analytics path
  // pushes this LLM-composed surface (A2uiSurface) instead of the fixed analytics_dashboard. It
  // matches none of the marketing/routing/workspace sets below, so the turn stays labeled analytics.
  a2ui_surface: A2uiSurfaceView,
  video_brief: VideoBriefCard,
  marketing_storyboard: StoryboardFilmstrip,
  marketing_script_timeline: ScriptTimeline,
  marketing_critique: CritiqueCard,
  marketing_render: MarketingRenderCard,
  route_map: RouteMapCard,
  workspace_actions: WorkspaceActionsCard,
};
// ui.name values that mark a turn as the marketing workflow (drives the ModeChip).
const MARKETING_UI = new Set([
  "video_brief",
  "marketing_storyboard",
  "marketing_script_timeline",
  "marketing_critique",
  "marketing_render",
]);

type ToolCall = { name: string; args: Record<string, unknown>; id?: string };

export function NoraAvatar() {
  return (
    <div className="flex size-[30px] shrink-0 items-center justify-center rounded-lg bg-ink font-mono text-[13px] font-semibold text-ink-foreground">
      N
    </div>
  );
}

type TurnMode = "analytics" | "marketing" | "routing" | "workspace";

// The mode chip beside "Nora": ink pill for the analytics agent, accent-tint pill for the marketing
// workflow, info-tint for the deterministic routing capability — the paradigms explicit at a glance.
function ModeChip({ mode }: { mode: TurnMode }) {
  if (mode === "marketing")
    return (
      <span className="rounded-full border border-brand-edge bg-brand-tint px-2 py-px text-[9.5px] font-semibold text-brand-text">
        Marketing workflow
      </span>
    );
  if (mode === "routing")
    return (
      <span className="rounded-full border border-info-edge bg-info-tint px-2 py-px text-[9.5px] font-semibold text-info-text">
        Operations
      </span>
    );
  if (mode === "workspace")
    return (
      <span className="rounded-full border border-info-edge bg-info-tint px-2 py-px text-[9.5px] font-semibold text-info-text">
        Workspace agent
      </span>
    );
  return (
    <span className="rounded-full bg-ink px-2 py-px text-[9.5px] font-semibold text-ink-foreground">
      Analytics agent
    </span>
  );
}

// ── Supervisor → subagent handoffs ─────────────────────────────────────────────────────────────
// The backend is a supervisor that delegates to a capability via a handoff tool-call (`to_analytics`
// / `to_marketing` / `to_workspace`, args carry the delegated `task`). A handoff AI message is the
// supervisor→subagent boundary; every message after it (until the next handoff) belongs to that
// subagent. We render the boundary as a DelegationBoundary and the subagent's run as a SubagentLane.

type HandoffTarget = "analytics" | "marketing" | "workspace";

const HANDOFF_TARGETS: Record<string, HandoffTarget> = {
  to_analytics: "analytics",
  to_marketing: "marketing",
  to_workspace: "workspace",
};

// Per-target visual language (matches ModeChip): ink for analytics, brand tint for marketing, info
// tint for workspace — used to colour the boundary marker and the lane rail/label.
const TARGET: Record<
  HandoffTarget,
  { label: string; pill: string; rail: string; accent: string; badge: string; badgeIcon: string }
> = {
  analytics: {
    label: "Analytics agent",
    pill: "bg-ink text-ink-foreground",
    rail: "bg-ink/25",
    accent: "text-foreground",
    badge: "border-border bg-muted",
    badgeIcon: "text-foreground/70",
  },
  marketing: {
    label: "Marketing workflow",
    pill: "border border-brand-edge bg-brand-tint text-brand-text",
    rail: "bg-brand-edge",
    accent: "text-brand-text",
    badge: "border-brand-edge bg-brand-tint",
    badgeIcon: "text-brand-text",
  },
  workspace: {
    label: "Workspace agent",
    pill: "border border-info-edge bg-info-tint text-info-text",
    rail: "bg-info-edge",
    accent: "text-info-text",
    badge: "border-info-edge bg-info-tint",
    badgeIcon: "text-info-text",
  },
};

// A supervisor→subagent handoff: an AI message whose tool-calls include a `to_*` capability tool.
// The backend honours only the FIRST such call per message (the rest get "Skipped" acks), so we
// read the first one; its `task` arg is the delegated instruction shown under the boundary.
function handoffOf(message: Message): { target: HandoffTarget; task?: string } | null {
  const toolCalls = (message as { tool_calls?: ToolCall[] }).tool_calls ?? [];
  for (const c of toolCalls) {
    const target = HANDOFF_TARGETS[c.name];
    if (target) {
      const task = typeof c.args?.task === "string" ? c.args.task : undefined;
      return { target, task };
    }
  }
  return null;
}

type Segment =
  | { kind: "boundary"; key: string; target: HandoffTarget; task?: string }
  | { kind: "lane"; key: string; target: HandoffTarget; messages: Message[] }
  | { kind: "plain"; key: string; message: Message };

// Walk a turn's assistant messages into ordered segments that make the supervisor↔subagent boundary
// explicit. On a handoff message: close any open lane, emit a DelegationBoundary, open a new lane
// for that target. Otherwise: push the message into the open lane (the subagent's work), or render
// it plainly when no lane is open (a supervisor clarification). The trailing lane is flushed at end.
function segmentTurn(messages: Message[]): Segment[] {
  const segments: Segment[] = [];
  let lane: { key: string; target: HandoffTarget; messages: Message[] } | null = null;
  const closeLane = () => {
    const cur = lane;
    if (cur) {
      segments.push({ kind: "lane", key: cur.key, target: cur.target, messages: cur.messages });
      lane = null;
    }
  };
  messages.forEach((message, i) => {
    const handoff = handoffOf(message);
    if (handoff) {
      closeLane();
      // Keyed off the handoff message's (stable) id, so a double-delegation to the same target
      // renders as two distinct boundaries + lanes rather than colliding on one key.
      const base = message.id ?? `seg-${i}`;
      segments.push({
        kind: "boundary",
        key: `b-${base}`,
        target: handoff.target,
        task: handoff.task,
      });
      lane = { key: `l-${base}`, target: handoff.target, messages: [] };
      return;
    }
    const open = lane;
    if (open) open.messages.push(message);
    else segments.push({ kind: "plain", key: `p-${message.id ?? `seg-${i}`}`, message });
  });
  closeLane();
  return segments;
}

// One assistant TURN: a single Nora header (avatar + name + ModeChip), then the ordered handover
// segments — delegation boundaries and the subagent lanes they open, plus any plain supervisor text.
// A compose (analytics→marketing) reads as two boundaries + two lanes; a double-delegation to the
// same target reads as two of each — faithful to whatever the supervisor actually did this turn.
export function AssistantTurn({
  messages,
  isLoading,
  isActive,
}: {
  messages: Message[];
  isLoading: boolean;
  // True only for the live, currently-streaming turn (the last turn while the stream is loading).
  // Gates the "still working" affordances (empty-lane dots, deferring the lane's "back to
  // supervisor" footer) so finished turns above never flicker when a NEW turn starts streaming.
  isActive: boolean;
}) {
  const stream = useStreamContext();
  const segments = segmentTurn(messages);

  // The turn's headline chip: the first capability it delegated to; else inferred from the cards it
  // pushed (route_map → routing); else a pure-supervisor turn (a clarification) → no capability chip.
  const firstHandoff = messages.reduce<ReturnType<typeof handoffOf>>(
    (found, m) => found ?? handoffOf(m),
    null,
  );
  const turnIds = new Set(messages.map((m) => m.id));
  const cards = (stream.values.ui ?? []).filter((ui) =>
    turnIds.has((ui.metadata as { message_id?: string } | undefined)?.message_id),
  );
  const mode: TurnMode | null = firstHandoff
    ? firstHandoff.target
    : cards.some((ui) => MARKETING_UI.has(ui.name))
      ? "marketing"
      : cards.some((ui) => ui.name === "route_map")
        ? "routing"
        : cards.some((ui) => ui.name === "workspace_actions")
          ? "workspace"
          : null;

  return (
    <div className="flex items-start gap-3">
      <NoraAvatar />
      <div className="min-w-0 flex-1 space-y-3">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold">Nora</span>
          {mode && <ModeChip mode={mode} />}
        </div>

        {segments.map((seg, i) => {
          if (seg.kind === "boundary") {
            return <DelegationBoundary key={seg.key} target={seg.target} task={seg.task} />;
          }
          if (seg.kind === "lane") {
            // The trailing lane of the live turn may still be receiving the subagent's output, so
            // defer its "back to supervisor" footer until the stream settles; older lanes show it.
            const trailing = i === segments.length - 1;
            return (
              <SubagentLane
                key={seg.key}
                target={seg.target}
                messages={seg.messages}
                isLoading={isLoading}
                active={isActive && trailing}
              />
            );
          }
          return (
            <MessageBody
              key={seg.key}
              message={seg.message}
              isLoading={isLoading}
              continuation={false}
            />
          );
        })}
      </div>
    </div>
  );
}

// The supervisor→subagent boundary, drawn as a prominent marker (NOT a tool-step card): an arrow
// motif + "Supervisor → <capability>" in the target's colour, with the delegated task as a subtitle.
// The "Handing off to…" ack ToolMessage is folded in here (it's never rendered as its own card —
// it's only ever surfaced via a tool-call's resultFor lookup, and a handoff call isn't rendered).
function DelegationBoundary({ target, task }: { target: HandoffTarget; task?: string }) {
  const t = TARGET[target];
  return (
    <div className="flex items-start gap-2.5">
      <div
        className={cn(
          "flex size-[22px] shrink-0 items-center justify-center rounded-md border",
          t.badge,
        )}
      >
        <ArrowRight className={cn("size-3.5", t.badgeIcon)} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 text-[12px] font-semibold">
          <span className="text-muted-foreground">Supervisor</span>
          <ArrowRight className="size-3 shrink-0 text-muted-foreground/60" />
          <span className={t.accent}>{t.label}</span>
        </div>
        {task && <p className="mt-1 text-[12px] leading-snug text-muted-foreground">{task}</p>}
      </div>
    </div>
  );
}

// The delegated capability's run, wrapped in a distinct lane: a left rail in the target's colour, a
// persistent capability label, the subagent's message bodies (tool steps + answer + reasoning +
// pushed gen-UI cards), and a subtle "back to supervisor" footer once control has returned.
function SubagentLane({
  target,
  messages,
  isLoading,
  active,
}: {
  target: HandoffTarget;
  messages: Message[];
  isLoading: boolean;
  // The live, trailing lane — defer the footer and show working dots while empty.
  active: boolean;
}) {
  const t = TARGET[target];
  return (
    <div className="relative pl-4">
      <div className={cn("absolute top-0.5 bottom-0.5 left-[3px] w-0.5 rounded-full", t.rail)} />
      <div className="mb-2 flex items-center gap-1.5">
        <span className={cn("rounded-full px-2 py-px text-[9.5px] font-semibold", t.pill)}>
          {t.label}
        </span>
      </div>
      {messages.length > 0 ? (
        <div className="space-y-2.5">
          {messages.map((m, i) => (
            <MessageBody
              key={m.id ?? `body-${i}`}
              message={m}
              isLoading={isLoading}
              continuation={i > 0}
            />
          ))}
        </div>
      ) : (
        active && <WorkingDots />
      )}
      {messages.length > 0 && !active && (
        <div className="mt-2.5 flex items-center gap-1 text-[10.5px] font-medium text-muted-foreground/70">
          <CornerUpLeft className="size-3" />
          back to supervisor
        </div>
      )}
    </div>
  );
}

function WorkingDots() {
  return (
    <div className="flex items-center gap-1 py-1">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="size-1.5 animate-pulse rounded-full bg-muted-foreground/50"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </div>
  );
}

// One assistant message's body — reasoning chain, answer bubble, tool steps, pushed gen-UI cards,
// and the copy/regenerate/branch actions — WITHOUT the Nora avatar/header (drawn once per turn by
// AssistantTurn). Used for both subagent-lane messages and plain supervisor messages. `continuation`
// threads the tool-step rail: the first body in a lane starts a fresh rail, later ones extend it.
function MessageBody({
  message,
  isLoading,
  continuation,
}: {
  message: Message;
  isLoading: boolean;
  continuation: boolean;
}) {
  const stream = useStreamContext();
  const [locked, runLocked] = useSubmitLock();
  const meta = stream.getMessagesMetadata(message);
  const parentCheckpoint = meta?.firstSeenState?.parent_checkpoint;

  const text = getContentString(message.content);
  const reasoning = getReasoningString(message);
  const toolCalls = (message as { tool_calls?: ToolCall[] }).tool_calls ?? [];
  // The reasoning chain is still "thinking" while this is the latest message, the turn is running,
  // and nothing's resolved on it yet (no answer text, no tool decision). Once text or tool calls
  // land — here or on a later message — the chain has resolved, so the card rests at "thought".
  const isLatest = stream.messages[stream.messages.length - 1]?.id === message.id;
  const reasoningRunning = isLoading && isLatest && !text && toolCalls.length === 0;
  // Pair each tool call with its result ToolMessage (matched by id) so a call + its result render
  // as one collapsible card — the ToolMessages themselves are consumed here, not rendered loose.
  const resultFor = (id?: string) =>
    id
      ? stream.messages.find((m) => (m as { tool_call_id?: string }).tool_call_id === id)
      : undefined;

  // push_ui_message UI messages tagged to this AI message (analytics dashboard, or the marketing
  // brief + storyboard/script/critique cards). Rendered regardless of whether the message has text.
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

  const regenerate = async () => {
    // Without the fork checkpoint, this would run from HEAD and append a new turn at the end instead
    // of regenerating THIS one as an alternate branch. Bail loudly. (If it fires, the turn's
    // checkpoint isn't in the fetched history — see fetchStateHistory in providers/Stream.tsx.)
    if (!parentCheckpoint) {
      toast.error("Can't regenerate this turn — its checkpoint hasn't loaded yet. Try again in a moment.");
      return;
    }
    // Carry the per-run config (Google token + Author-UI mode) so regenerating a workspace turn
    // doesn't run tokenless and degrade to the "connect" stub — see lib/run-config.ts.
    const runConfig = await buildSubmitConfig();
    stream.submit(undefined, {
      checkpoint: parentCheckpoint,
      streamMode: ["values"],
      streamSubgraphs: true,
      ...runConfig,
    });
  };

  return (
    <div className="group space-y-2">
      {/* The model's reasoning chain (Anthropic extended thinking) — drawn before the answer/
          tool steps it produced. Empty for non-reasoning models (e.g. gpt-4o), so it renders
          nothing by default. */}
      {reasoning && <ReasoningStep reasoning={reasoning} running={reasoningRunning} />}

      {text && (
        <div className="rounded-[5px_13px_13px_13px] border bg-card px-[15px] py-[13px] text-[13.5px] leading-[1.55]">
          <MarkdownText>{text}</MarkdownText>
        </div>
      )}

      {toolCalls.length > 0 && (
        // One AI message's tool calls = one step. Calls in the same message ran in PARALLEL
        // (ToolNode fires them together); a later message is a SEQUENTIAL step. Thread them.
        <ToolStepGroup calls={toolCalls} resultFor={resultFor} continuation={continuation} />
      )}

      {uiForMessage.map((ui) => (
        // Per-card boundary: a card that throws on a partial/streaming payload degrades to a small
        // inline notice instead of unwinding to the page-root ChatErrorBoundary (h-dvh) and blanking
        // the whole screen. resetKeys tracks the streamed props, so the card re-renders the moment
        // complete data lands.
        <CardErrorBoundary
          key={ui.id}
          label={ui.name}
          resetKeys={[JSON.stringify(ui.props ?? null)]}
        >
          <LoadExternalComponent
            // Cast at the boundary: LoadExternalComponent's prop types are deliberately loose
            // (Record<string, unknown> state, {}-prop components); our typed stream + dashboard
            // component are stricter. Runtime behaviour is correct (ui.props → AnalyticsDashboard).
            stream={stream as ComponentProps<typeof LoadExternalComponent>["stream"]}
            message={ui}
            components={
              UI_COMPONENTS as unknown as ComponentProps<typeof LoadExternalComponent>["components"]
            }
          />
        </CardErrorBoundary>
      ))}

      {/* Actions sit on the message that carries the final text answer. The row also renders for a
          text-less message when it has alternate branches, so branch nav is never hidden. */}
      {(text || (meta?.branchOptions?.length ?? 0) > 1) && (
        <div className="flex items-center gap-1">
          {/* Branch nav stays VISIBLE whenever alternates exist (regenerating forks a branch). */}
          <BranchSwitcher
            branch={meta?.branch}
            branchOptions={meta?.branchOptions}
            onSelect={(b) => stream.setBranch(b)}
            disabled={isLoading}
          />
          <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
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
              disabled={isLoading || locked}
              onClick={() => runLocked(regenerate)}
              className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
            >
              <RefreshCw className="size-3.5" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// The model's reasoning chain (Anthropic extended thinking), as a thin collapsible card matching
// the tool-step cards it sits beside. Collapsed by default (the chain can be long); the header
// pulses "thinking…" while it's still streaming, then rests at "thought". Expanding reveals the raw
// chain-of-thought. Only mounted when there's reasoning to show, so non-reasoning models render
// nothing.
function ReasoningStep({ reasoning, running }: { reasoning: string; running: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="overflow-hidden rounded-lg border bg-muted/30 text-xs">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-left font-mono text-muted-foreground transition-colors hover:bg-muted/50"
      >
        <ChevronRight className={cn("size-3 shrink-0 transition-transform", open && "rotate-90")} />
        <Brain className="size-3 shrink-0 text-muted-foreground/70" />
        <span className="font-medium text-foreground/80">reasoning</span>
        <span className={cn("truncate text-muted-foreground/80", running && "animate-pulse")}>
          · {running ? "thinking…" : "thought"}
        </span>
      </button>

      {open && (
        <div className="border-t bg-background/40 px-2.5 py-2">
          <pre className="max-h-48 overflow-auto font-mono text-[11px] break-words whitespace-pre-wrap text-muted-foreground italic">
            {reasoning || "…"}
          </pre>
        </div>
      )}
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
                className="size-1 animate-pulse rounded-full bg-current"
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
          <span key={i} className="font-semibold text-info">
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
  const rows = rest.flatMap((r) => (r.length > 0 ? [r.split(" | ")] : []));
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
            {parsed.columns.map((col) => (
              <th key={col} className="border-b px-2 py-1 text-left font-medium whitespace-nowrap">
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
