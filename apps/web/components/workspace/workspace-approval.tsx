"use client";

import { useState } from "react";
import { Check, Mail, Pencil, X } from "lucide-react";

import { NoraAvatar } from "@/components/thread/messages/ai";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { WorkspaceApprovalInterrupt, WorkspaceDecision } from "@/lib/types";
import { useStreamContext } from "@/providers/Stream";
import { cn } from "@/lib/utils";

// The workspace write-approval gate — a single HITL surface for BOTH backend mechanisms:
//   - path B ("primitive"): the hand-written loop's batched interrupt() — payload tags `kind:
//     "workspace_approval"` and carries one `action_requests` entry per pending write.
//   - path A ("middleware"): create_agent + HumanInTheLoopMiddleware — same `action_requests`, plus
//     `review_configs`; no `kind`.
// Both resume with the same `Command(resume={ decisions: [...] })`, one decision per action in order,
// so this one component drives either. Rendered inline in the thread (like ConceptPicker) and resumes
// the paused run right here on the same thread.
export function WorkspaceApproval({ interrupt }: { interrupt: WorkspaceApprovalInterrupt }) {
  const stream = useStreamContext();
  const busy = stream.isLoading;
  const actions = interrupt.action_requests ?? [];

  const [editing, setEditing] = useState(false);
  // Per-action editable args (pretty JSON), seeded from the proposed call. Reading `args ?? arguments`
  // tolerates either payload key; the installed middleware uses `args`, same as path B.
  const [drafts, setDrafts] = useState<string[]>(() =>
    actions.map((a) => JSON.stringify(a.args ?? a.arguments ?? {}, null, 2)),
  );

  // Each draft must be valid JSON before we can approve (an edited call has to serialize).
  const invalid = editing && drafts.some((d) => !isJson(d));

  const resume = (decisions: WorkspaceDecision[]) => {
    stream.submit(undefined, {
      command: { resume: { decisions } },
      streamMode: ["values"],
      streamSubgraphs: true,
    });
  };

  const approve = () => {
    const decisions: WorkspaceDecision[] = actions.map((a, i) => {
      if (!editing) return { type: "approve" };
      const args = JSON.parse(drafts[i]);
      // Only mark it an edit if the operator actually changed the args; otherwise plain approve.
      const changed = JSON.stringify(args) !== JSON.stringify(a.args ?? a.arguments ?? {});
      return changed ? { type: "edit", edited_action: { name: a.name, args } } : { type: "approve" };
    });
    resume(decisions);
  };

  const reject = () =>
    resume(
      actions.map(() => ({
        type: "reject",
        message: "The operator declined this action.",
      })),
    );

  return (
    <div className="flex items-start gap-3">
      <NoraAvatar />
      <div className="min-w-0 flex-1 space-y-2.5">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold">Nora</span>
          <span className="rounded-full border border-brand-edge bg-brand-tint px-2 py-px text-[9.5px] font-semibold text-brand-text">
            Workspace · awaiting approval
          </span>
        </div>
        <p className="text-[13.5px] text-muted-foreground">
          {interrupt.question ??
            "Approve these Google Workspace actions before Nora runs them?"}
        </p>

        <div className="flex flex-col gap-2.5">
          {actions.map((a, i) => (
            <div
              key={a.id ?? `${a.name}-${i}`}
              className="rounded-[10px] border border-brand-edge bg-card p-3"
            >
              <div className="flex items-center gap-2">
                <Mail className="size-4 shrink-0 text-brand" />
                <span className="font-mono text-[12.5px] font-semibold">{a.name}</span>
              </div>
              {editing ? (
                <Textarea
                  rows={Math.min(10, drafts[i].split("\n").length + 1)}
                  value={drafts[i]}
                  onChange={(e) =>
                    setDrafts((prev) => prev.map((d, j) => (j === i ? e.target.value : d)))
                  }
                  className={cn(
                    "mt-2 resize-y font-mono text-[12px]",
                    !isJson(drafts[i]) && "border-danger-edge",
                  )}
                />
              ) : (
                <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words rounded-[6px] bg-body-bg px-2.5 py-2 font-mono text-[12px] leading-[1.5]">
                  {JSON.stringify(a.args ?? a.arguments ?? {}, null, 2)}
                </pre>
              )}
            </div>
          ))}
        </div>

        <div className="flex items-center gap-2.5 pt-0.5">
          <Button size="sm" disabled={busy || invalid} onClick={approve}>
            <Check className="size-3.5" />
            {editing ? "Approve edited" : "Approve & run"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => setEditing((e) => !e)}
          >
            <Pencil className="size-3.5" />
            {editing ? "Cancel edit" : "Edit"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            className="border-danger-edge text-danger-text hover:bg-danger-tint/40"
            onClick={reject}
          >
            <X className="size-3.5" />
            Reject
          </Button>
          {invalid && (
            <span className="font-mono text-[10.5px] text-danger-text">Fix invalid JSON</span>
          )}
        </div>
      </div>
    </div>
  );
}

function isJson(s: string): boolean {
  try {
    JSON.parse(s);
    return true;
  } catch {
    return false;
  }
}
