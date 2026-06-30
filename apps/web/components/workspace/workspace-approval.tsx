"use client";

import { useState } from "react";
import { Calendar, Check, FileText, Mail, Pencil, Wrench, X } from "lucide-react";

import { NoraAvatar } from "@/components/thread/messages/ai";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type {
  ApprovalLayout,
  ApprovalLayoutField,
  WorkspaceActionRequest,
  WorkspaceApprovalInterrupt,
  WorkspaceDecision,
} from "@/lib/types";
import { buildSubmitConfig } from "@/lib/run-config";
import { useSubmitLock } from "@/lib/use-submit-lock";
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
  const [locked, runLocked] = useSubmitLock();
  const actions = interrupt.action_requests ?? [];

  const [editing, setEditing] = useState(false);
  // Per-action editable FIELDS, seeded from the proposed call's LITERAL args (the source of truth the
  // layout is derived from). Each arg becomes a typed field so the operator edits a real form — text /
  // multi-line / checkbox / number — instead of hand-editing raw JSON. Reading `args ?? arguments`
  // tolerates either payload key; the installed middleware uses `args`, same as path B.
  const [fields, setFields] = useState<EditField[][]>(() => actions.map((a) => toFields(argsOf(a))));

  const updateField = (ai: number, fi: number, value: string | boolean) =>
    setFields((prev) =>
      prev.map((fs, a) => (a === ai ? fs.map((f, j) => (j === fi ? { ...f, value } : f)) : fs)),
    );

  // Entering edit reseeds from the proposal; "Cancel edit" discards in-progress edits back to it.
  const toggleEdit = () => {
    if (editing) setFields(actions.map((a) => toFields(argsOf(a))));
    setEditing((e) => !e);
  };

  // Only un-approvable when a value can't be coerced back to its type (bad JSON in a nested field, or
  // a non-numeric number). Scalar text/checkbox fields are always valid.
  const invalid = editing && fields.some((fs) => fs.some(fieldInvalid));

  const resume = async (decisions: WorkspaceDecision[]) => {
    // Carry the per-run config (Google token + Author-UI mode) so the RESUMED run isn't tokenless: the
    // `workspace` node re-runs from the top and re-reads the token from run config, so without it the
    // approved action degrades to the "connect" stub instead of executing. See lib/run-config.ts.
    const runConfig = await buildSubmitConfig();
    stream.submit(undefined, {
      command: { resume: { decisions } },
      streamMode: ["values"],
      streamSubgraphs: true,
      ...runConfig,
    });
  };

  const approve = () =>
    runLocked(async () => {
      const decisions: WorkspaceDecision[] = actions.map((a, i) => {
        if (!editing) return { type: "approve" };
        const args = fromFields(fields[i]);
        // Only mark it an edit if the operator actually changed the args; otherwise plain approve.
        const changed = JSON.stringify(args) !== JSON.stringify(argsOf(a));
        return changed ? { type: "edit", edited_action: { name: a.name, args } } : { type: "approve" };
      });
      await resume(decisions);
    });

  const reject = () =>
    runLocked(() =>
      resume(
        actions.map(() => ({
          type: "reject",
          message: "The operator declined this action.",
        })),
      ),
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
                  // Edit operates on the LITERAL args — the source of truth the layout derives from —
                  // but as a real form: one typed input per arg, not a raw-JSON blob.
                  <div className="mt-2.5 flex flex-col gap-2.5">
                    {fields[i].map((f, j) => (
                      <div key={f.key} className="flex flex-col gap-1">
                        <label className="text-[10.5px] font-semibold uppercase tracking-wide text-muted-foreground">
                          {humanize(f.key)}
                        </label>
                        {f.kind === "boolean" ? (
                          <label className="flex w-fit cursor-pointer items-center gap-2 text-[13px]">
                            <input
                              type="checkbox"
                              checked={f.value === true}
                              onChange={(e) => updateField(i, j, e.target.checked)}
                              className="size-3.5 accent-brand"
                            />
                            <span className="text-muted-foreground">{f.value ? "Yes" : "No"}</span>
                          </label>
                        ) : f.kind === "textarea" || f.kind === "json" ? (
                          <Textarea
                            rows={Math.min(10, String(f.value).split("\n").length + 1)}
                            value={String(f.value)}
                            onChange={(e) => updateField(i, j, e.target.value)}
                            className={cn(
                              "resize-y text-[13px]",
                              f.kind === "json" && "font-mono text-[12px]",
                              fieldInvalid(f) && "border-danger-edge",
                            )}
                          />
                        ) : (
                          <Input
                            type={f.kind === "number" ? "number" : "text"}
                            value={String(f.value)}
                            onChange={(e) => updateField(i, j, e.target.value)}
                            className={cn("text-[13px]", fieldInvalid(f) && "border-danger-edge")}
                          />
                        )}
                        {f.kind === "json" && fieldInvalid(f) && (
                          <span className="font-mono text-[10px] text-danger-text">Invalid JSON</span>
                        )}
                      </div>
                    ))}
                  </div>
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
          <Button size="sm" disabled={busy || locked || invalid} onClick={approve}>
            <Check className="size-3.5" />
            {editing ? "Approve edited" : "Approve & run"}
          </Button>
          <Button size="sm" variant="outline" disabled={busy || locked} onClick={toggleEdit}>
            <Pencil className="size-3.5" />
            {editing ? "Cancel edit" : "Edit"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={busy || locked}
            className="border-danger-edge text-danger-text hover:bg-danger-tint/40"
            onClick={reject}
          >
            <X className="size-3.5" />
            Reject
          </Button>
          {invalid && (
            <span className="font-mono text-[10.5px] text-danger-text">Fix the highlighted fields</span>
          )}
        </div>
      </div>
    </div>
  );
}

// One editable form field per literal arg, typed so we can render the right control and coerce the
// value back on approve. Nested objects/arrays fall back to a validated JSON textarea so nothing is
// un-editable.
type EditFieldKind = "text" | "textarea" | "number" | "boolean" | "json";
type EditField = { key: string; kind: EditFieldKind; value: string | boolean };

function argsOf(a: WorkspaceActionRequest): Record<string, unknown> {
  return (a.args ?? a.arguments ?? {}) as Record<string, unknown>;
}

function toFields(args: Record<string, unknown>): EditField[] {
  return Object.entries(args).map(([key, v]) => {
    if (typeof v === "boolean") return { key, kind: "boolean", value: v };
    if (typeof v === "number") return { key, kind: "number", value: String(v) };
    if (typeof v === "string")
      return { key, kind: v.length > 60 || v.includes("\n") ? "textarea" : "text", value: v };
    return { key, kind: "json", value: JSON.stringify(v, null, 2) };
  });
}

// Rebuild the args object, coercing each field back to its original type. Safe only when no field is
// invalid (Approve is disabled otherwise), since the JSON/number parses can throw/NaN.
function fromFields(fields: EditField[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    if (f.kind === "boolean") out[f.key] = Boolean(f.value);
    else if (f.kind === "number") out[f.key] = Number(f.value);
    else if (f.kind === "json") out[f.key] = JSON.parse(String(f.value));
    else out[f.key] = String(f.value);
  }
  return out;
}

function fieldInvalid(f: EditField): boolean {
  if (f.kind === "json") {
    try {
      JSON.parse(String(f.value));
      return false;
    } catch {
      return true;
    }
  }
  if (f.kind === "number") return f.value !== "" && Number.isNaN(Number(f.value));
  return false;
}
