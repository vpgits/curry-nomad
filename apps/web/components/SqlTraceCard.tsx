"use client";

import { useState } from "react";
import { ChevronDown, Database, GitFork, Terminal } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ToolCallTrace, ToolTraceStep } from "@/lib/types";

// Renders the analytics agent's work — the steps the orchestrator folds onto its final message as
// `additional_kwargs.tool_trace`. Each step is one turn of the agent loop: calls in the same step
// ran in parallel; steps run in sequence (each saw the previous results, including a SQL error it
// then repairs). Shows request *and* response per call. Collapsed by default to keep answers clean.
export function SqlTraceCard({ trace }: { trace: ToolTraceStep[] }) {
  const [open, setOpen] = useState(false);
  // Tolerate the pre-steps trace shape persisted in older threads' checkpoints: drop anything
  // that isn't a well-formed step rather than crashing on a missing `calls`.
  const steps = trace.filter((s) => Array.isArray(s?.calls));
  if (steps.length === 0) return null;

  const callCount = steps.reduce((n, step) => n + step.calls.length, 0);
  const stepLabel = `${steps.length} ${steps.length === 1 ? "step" : "steps"}`;
  const callLabel = `${callCount} ${callCount === 1 ? "call" : "calls"}`;

  return (
    <div className="rounded-lg border bg-muted/30 text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-muted-foreground hover:text-foreground"
        aria-expanded={open}
      >
        <Database className="size-3.5 shrink-0" />
        <span className="font-medium">
          Agent&apos;s work · {stepLabel} · {callLabel}
        </span>
        <ChevronDown className={cn("ml-auto size-4 transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="space-y-3 border-t px-3 py-3">
          {steps.map((step, i) => (
            <Step key={i} step={step} index={i} />
          ))}
        </div>
      )}
    </div>
  );
}

function Step({ step, index }: { step: ToolTraceStep; index: number }) {
  const parallel = step.calls.length > 1;
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
        <span>Step {index + 1}</span>
        {parallel && (
          <span className="inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] normal-case">
            <GitFork className="size-2.5" />
            {step.calls.length} in parallel
          </span>
        )}
      </div>
      <div className="space-y-2 border-l-2 border-border pl-3">
        {step.calls.map((call, i) => (
          <Call key={i} call={call} />
        ))}
      </div>
    </div>
  );
}

function Call({ call }: { call: ToolCallTrace }) {
  // run_sql carries the SQL under `query`; show it as code. Other tools show their args as JSON.
  const query = typeof call.args.query === "string" ? call.args.query : null;
  const request = query ?? JSON.stringify(call.args, null, 2);

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5 font-mono text-muted-foreground">
        <Terminal className="size-3 shrink-0" />
        {call.name}
      </div>

      <Labeled label="Request">
        <pre className="overflow-x-auto rounded-md border bg-background p-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">
          {request}
        </pre>
      </Labeled>

      {call.result && (
        <Labeled label="Response">
          <Result text={call.result} />
        </Labeled>
      )}
    </div>
  );
}

function Labeled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <div className="text-[10px] font-medium tracking-wide text-muted-foreground/70 uppercase">
        {label}
      </div>
      {children}
    </div>
  );
}

const RESULT_LIMIT = 600;

function Result({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const long = text.length > RESULT_LIMIT;
  const shown = expanded || !long ? text : text.slice(0, RESULT_LIMIT) + "…";

  return (
    <div className="space-y-1">
      <pre className="max-h-72 overflow-auto rounded-md border bg-background p-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">
        {shown}
      </pre>
      {long && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="text-[11px] text-muted-foreground hover:text-foreground"
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}
