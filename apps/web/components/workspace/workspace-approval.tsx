"use client";

import { useState } from "react";
import { Calendar, Check, FileText, Mail, Pencil, Wrench, X } from "lucide-react";

import { NoraAvatar } from "@/components/thread/messages/ai";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type {
  ApprovalLayout,
  ApprovalLayoutField,
  WorkspaceActionRequest,
  WorkspaceApprovalInterrupt,
  WorkspaceDecision,
} from "@/lib/types";
import { useStreamContext } from "@/providers/Stream";
import { cn } from "@/lib/utils";

const APPROVAL_ICONS = {
  email: Mail,
  calendar: Calendar,
  document: FileText,
  generic: Wrench,
} as const;

function humanize(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Faithful fallback when the backend didn't AI-author a layout (the middleware path, or no model):
// build the card from the LITERAL args, picking an icon/title from the tool name. Values are the real
// args verbatim — never paraphrased — so the approver still sees exactly what will run.
function fallbackLayout(a: WorkspaceActionRequest): ApprovalLayout {
  const args = (a.args ?? a.arguments ?? {}) as Record<string, unknown>;
  const n = a.name.toLowerCase();
  const icon: ApprovalLayout["icon"] = /gmail|email|mail/.test(n)
    ? "email"
    : /calendar|event/.test(n)
      ? "calendar"
      : /doc|file|sheet|drive/.test(n)
        ? "document"
        : "generic";
  const fields: ApprovalLayoutField[] = Object.entries(args).map(([k, v]) => {
    const value = typeof v === "string" ? v : JSON.stringify(v, null, 2);
    return { label: humanize(k), value, style: value.length > 80 ? "block" : "inline" };
  });
  return { icon, title: humanize(a.name), fields };
}

function resolveLayout(a: WorkspaceActionRequest): ApprovalLayout {
  return a.layout && Array.isArray(a.layout.fields) ? a.layout : fallbackLayout(a);
}

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
          {actions.map((a, i) => {
            const layout = resolveLayout(a);
            const Icon = APPROVAL_ICONS[layout.icon] ?? Wrench;
            return (
              <div
                key={a.id ?? `${a.name}-${i}`}
                className="rounded-[10px] border border-brand-edge bg-card p-3"
              >
                <div className="flex items-center gap-2">
                  <Icon className="size-4 shrink-0 text-brand" />
                  <span className="text-[13px] font-semibold">{layout.title}</span>
                  <span className="ml-auto rounded-full bg-body-bg px-2 py-px font-mono text-[10px] text-muted-foreground">
                    {a.name}
                  </span>
                </div>
                {editing ? (
                  // Edit operates on the LITERAL args (JSON) — the source of truth the layout derives from.
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
                  <dl className="mt-2.5 flex flex-col gap-2">
                    {layout.fields.map((f, j) => (
                      <div
                        key={`${f.label}-${j}`}
                        className={cn(f.style === "block" ? "flex flex-col gap-1" : "flex items-baseline gap-2")}
                      >
                        <dt className="shrink-0 text-[10.5px] font-semibold uppercase tracking-wide text-muted-foreground">
                          {f.label}
                        </dt>
                        <dd
                          className={cn(
                            "break-words text-[13px] leading-[1.5]",
                            f.style === "block" &&
                              "whitespace-pre-wrap rounded-[6px] bg-body-bg px-2.5 py-2",
                          )}
                        >
                          {f.value}
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
              </div>
            );
          })}
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
