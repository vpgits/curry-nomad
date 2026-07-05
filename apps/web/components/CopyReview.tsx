"use client";

import { useState } from "react";
import { Check, Pencil, RefreshCw, X } from "lucide-react";
import { useQueryState } from "nuqs";

import { NoraAvatar } from "@/components/thread/messages/ai";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { ReviewDecision, ReviewInterrupt, Verbosity } from "@/lib/types";
import { buildSubmitConfig } from "@/lib/run-config";
import { logHitlStep } from "@/lib/hitl-log";
import { useSubmitLock } from "@/lib/use-submit-lock";
import { cn } from "@/lib/utils";
import { useStreamContext } from "@/providers/Stream";

const VERBOSITIES: Verbosity[] = ["concise", "standard", "detailed"];

// The copy-review HITL gate, INLINE in the /ask conversation (mirrors ConceptPicker / StillReview —
// no /briefs detour, no navigation). The operator reviews/edits the caption + per-image on-screen
// text, tunes the post settings (image count + caption verbosity) and regenerates — free here, since
// images only render after approval — or approves/rejects, all resuming the paused run in place.
// Rendered when stream.interrupt.value.kind === "copy_review". Key it on `interrupt.caption` at the
// call site so a regenerated draft re-seeds the local edit state.
export function CopyReview({ interrupt }: { interrupt: ReviewInterrupt }) {
  const stream = useStreamContext();
  const busy = stream.isLoading;
  const [locked, runLocked] = useSubmitLock();
  const [threadId] = useQueryState("threadId");

  const [editing, setEditing] = useState(false);
  const [caption, setCaption] = useState(interrupt.caption ?? "");
  const [onScreen, setOnScreen] = useState<string[]>(interrupt.on_screen_texts ?? []);
  const [numImages, setNumImages] = useState(interrupt.num_images ?? 4);
  const [verbosity, setVerbosity] = useState<Verbosity>(interrupt.verbosity ?? "standard");

  const setLine = (i: number, value: string) =>
    setOnScreen((prev) => prev.map((t, j) => (j === i ? value : t)));

  // Carry the run config on resume (Google token + Author-UI mode) — it isn't persisted across an
  // interrupt, so a marketing→workspace chain resumed here would otherwise reach the workspace node
  // tokenless. Then record the decision so it stays in the conversation loop after the gate clears.
  const resume = (decision: ReviewDecision, log: (anchorId?: string) => void) =>
    runLocked(async () => {
      const runConfig = await buildSubmitConfig();
      // Anchor the record to the message this decision followed (captured before submit appends new
      // ones) so it renders inline at the right turn, not in a flat bottom list.
      const anchorId = stream.messages[stream.messages.length - 1]?.id;
      stream.submit(undefined, {
        command: { resume: decision },
        streamMode: ["values"],
        streamSubgraphs: true,
        ...runConfig,
      });
      log(anchorId);
    });

  const approve = () =>
    resume(
      editing
        ? { approved: true, edited_copy: { caption, on_screen_texts: onScreen } }
        : { approved: true },
      (anchorId) =>
        logHitlStep(threadId, {
          icon: "approve",
          label: `Copy approved · ${numImages} images · ${verbosity}`,
          anchorId,
        }),
    );
  const reject = () =>
    resume({ approved: false }, (anchorId) =>
      logHitlStep(threadId, { icon: "reject", label: "Copy rejected", anchorId }),
    );
  const regenerate = () =>
    resume({ regenerate: true, num_images: numImages, verbosity }, (anchorId) =>
      logHitlStep(threadId, {
        icon: "regen",
        label: `Regenerated copy · ${numImages} images · ${verbosity}`,
        anchorId,
      }),
    );

  return (
    <div className="flex items-start gap-3">
      <NoraAvatar />
      <div className="min-w-0 flex-1 space-y-3">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold">Nora</span>
          <span className="rounded-full border border-brand-edge bg-brand-tint px-2 py-px text-[9.5px] font-semibold text-brand-text">
            Marketing workflow
          </span>
        </div>
        <p className="text-[13.5px] text-muted-foreground">{interrupt.question}</p>

        <div className="space-y-4 rounded-[13px] border border-brand-edge bg-brand-tint/20 p-4">
          {/* caption */}
          <div>
            <div className="mb-1.5 text-[12px] font-semibold">Caption</div>
            {editing ? (
              <Textarea
                rows={5}
                value={caption}
                onChange={(e) => setCaption(e.target.value)}
                className="resize-y border-brand-edge bg-card text-[13px]"
              />
            ) : (
              <p className="text-[13px] leading-[1.6] whitespace-pre-line">{caption}</p>
            )}
          </div>

          {/* on-screen text */}
          {onScreen.length > 0 && (
            <div>
              <div className="mb-1.5 text-[12px] font-semibold">On-screen text</div>
              <div className="flex flex-col gap-1.5">
                {onScreen.map((line, i) => (
                  <div
                    key={i}
                    className={cn(
                      "pl-3",
                      editing ? "border-l-2 border-brand" : "border-l-2 border-ink/40",
                    )}
                  >
                    <div className="font-mono text-[10px] text-muted-foreground">Image {i + 1}</div>
                    {editing ? (
                      <Textarea
                        rows={1}
                        value={line}
                        onChange={(e) => setLine(i, e.target.value)}
                        className="mt-1 resize-y border-brand-edge bg-card text-[13px]"
                      />
                    ) : (
                      <p className="text-[13px] leading-[1.5]">{line}</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* post settings — caption verbosity + image count, then regenerate */}
          <div className="flex flex-wrap items-end gap-x-5 gap-y-3 border-t border-brand-edge/60 pt-3.5">
            <div>
              <div className="mb-1.5 text-[11px] font-medium text-muted-foreground">
                Caption length
              </div>
              <div className="flex gap-1.5">
                {VERBOSITIES.map((v) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => setVerbosity(v)}
                    aria-pressed={verbosity === v}
                    className={cn(
                      "rounded-[7px] border px-2.5 py-1 text-[11px] font-medium capitalize transition-colors",
                      verbosity === v
                        ? "border-brand-edge bg-brand-tint text-brand-text"
                        : "border-border bg-card text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {v}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div className="mb-1.5 text-[11px] font-medium text-muted-foreground">Images</div>
              <div className="inline-flex items-center gap-3 rounded-[8px] border border-border bg-card px-2.5 py-1">
                <button
                  type="button"
                  onClick={() => setNumImages((n) => Math.max(1, n - 1))}
                  disabled={numImages <= 1}
                  className="text-[16px] leading-none text-muted-foreground hover:text-foreground disabled:opacity-40"
                  aria-label="Fewer images"
                >
                  −
                </button>
                <span className="min-w-4 text-center font-mono text-[13px] font-semibold tabular-nums">
                  {numImages}
                </span>
                <button
                  type="button"
                  onClick={() => setNumImages((n) => Math.min(8, n + 1))}
                  disabled={numImages >= 8}
                  className="text-[16px] leading-none text-muted-foreground hover:text-foreground disabled:opacity-40"
                  aria-label="More images"
                >
                  +
                </button>
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={busy || locked}
              onClick={regenerate}
              className="rounded-[8px]"
            >
              <RefreshCw className="size-3.5" /> Regenerate copy
            </Button>
            <span className="text-[10.5px] text-muted-foreground">
              Free — images render after you approve.
            </span>
          </div>
        </div>

        {/* actions */}
        <div className="flex flex-wrap items-center gap-2.5">
          <Button size="sm" disabled={busy || locked} onClick={approve} className="rounded-[8px]">
            <Check className="size-3.5" /> Approve &amp; continue
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={busy || locked}
            onClick={() => setEditing((e) => !e)}
            className="rounded-[8px]"
          >
            <Pencil className="size-3.5" /> {editing ? "Cancel edit" : "Edit copy"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={busy || locked}
            onClick={reject}
            className="rounded-[8px] border-danger-edge text-danger-text hover:bg-danger-tint/40"
          >
            <X className="size-3.5" /> Reject
          </Button>
        </div>
      </div>
    </div>
  );
}
