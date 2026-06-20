"use client";

import { useState } from "react";
import { ChevronDown, Database, Terminal } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ToolTraceEntry } from "@/lib/types";

// Renders the analytics agent's work — the run_sql / describe_table calls the orchestrator folds
// onto its final message as `additional_kwargs.tool_trace`. Makes the "agent wrote and ran SQL,
// self-correcting on errors" mechanism visible. Collapsed by default to keep answers clean.
export function SqlTraceCard({ trace }: { trace: ToolTraceEntry[] }) {
  const [open, setOpen] = useState(false);
  if (trace.length === 0) return null;

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
          Agent&apos;s work · {trace.length} {trace.length === 1 ? "call" : "calls"}
        </span>
        <ChevronDown className={cn("ml-auto size-4 transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="space-y-2 border-t px-3 py-2">
          {trace.map((entry, i) => (
            <TraceEntry key={i} entry={entry} />
          ))}
        </div>
      )}
    </div>
  );
}

function TraceEntry({ entry }: { entry: ToolTraceEntry }) {
  // run_sql carries the SQL under `query`; show it as code. Other tools show their args as JSON.
  const query = typeof entry.args.query === "string" ? entry.args.query : null;
  const rest = Object.entries(entry.args).filter(([k]) => k !== "query");

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1.5 font-mono text-muted-foreground">
        <Terminal className="size-3 shrink-0" />
        {entry.name}
      </div>
      {query && (
        <pre className="overflow-x-auto rounded-md border bg-background p-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">
          {query}
        </pre>
      )}
      {rest.length > 0 && (
        <pre className="overflow-x-auto rounded-md border bg-background p-2 font-mono text-[11px]">
          {JSON.stringify(Object.fromEntries(rest), null, 2)}
        </pre>
      )}
    </div>
  );
}
