"use client";

import { useState } from "react";
import { Check, RefreshCw } from "lucide-react";
import { useQueryState } from "nuqs";

import { NoraAvatar } from "@/components/thread/messages/ai";
import { Button } from "@/components/ui/button";
import { OPS_API_URL } from "@/lib/config";
import type { StillReviewInterrupt } from "@/lib/types";
import { buildSubmitConfig } from "@/lib/run-config";
import { logHitlStep } from "@/lib/hitl-log";
import { useSubmitLock } from "@/lib/use-submit-lock";
import { cn } from "@/lib/utils";
import { useStreamContext } from "@/providers/Stream";

// A relative /media path (e.g. "/media/<id>/hero.png") is served by the ops-api; make it absolute.
const mediaUrl = (path?: string | null) => (path ? `${OPS_API_URL}${path}` : undefined);

// The visual HITL gate: the marketing workflow's generated stills, surfaced for review BEFORE the
// Instagram post is finalized. The operator approves them all (→ finalize_post) or selects shots to
// re-roll (→ regenerate_stills, which loops back here) — the interrupt/resume pattern on the same
// thread, mirroring ConceptPicker. Rendered inline when interrupt.value.kind === "still_review".
export function StillReview({ interrupt }: { interrupt: StillReviewInterrupt }) {
  const stream = useStreamContext();
  const busy = stream.isLoading;
  const [locked, runLocked] = useSubmitLock();
  const [threadId] = useQueryState("threadId");
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const toggle = (index: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });

  // Carry the run config (Google token + Author-UI mode) on resume — it is NOT persisted across an
  // interrupt (same rationale as ConceptPicker). The lock blocks a double-fire during the fetch.
  const resume = (decision: Record<string, unknown>, log: (anchorId?: string) => void) =>
    runLocked(async () => {
      const runConfig = await buildSubmitConfig();
      // Anchor to the message this decision followed so the record renders inline at the right turn.
      const anchorId = stream.messages[stream.messages.length - 1]?.id;
      stream.submit(undefined, {
        command: { resume: decision },
        streamMode: ["values"],
        streamSubgraphs: true,
        ...runConfig,
      });
      log(anchorId);
    });

  // The hero image is index -1 (the backend re-rolls it when -1 is in the regenerate list).
  const tiles = [
    { index: -1, url: mediaUrl(interrupt.hero_image_url), label: "Hero image" },
    ...interrupt.shots.map((s) => ({
      index: s.index,
      url: mediaUrl(s.image_url),
      label: s.scene_description ?? `Image ${s.index + 1}`,
    })),
  ];

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
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {tiles.map((t) => {
            const marked = selected.has(t.index);
            return (
              <button
                key={t.index}
                type="button"
                onClick={() => toggle(t.index)}
                aria-pressed={marked}
                className={cn(
                  "flex flex-col overflow-hidden rounded-[11px] border text-left transition-colors",
                  marked
                    ? "border-brand ring-2 ring-brand/40"
                    : "border-border hover:border-brand-edge",
                )}
              >
                <div className="aspect-[9/16] w-full bg-muted">
                  {t.url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={t.url} alt={t.label} className="size-full object-cover" />
                  ) : (
                    <div className="flex size-full items-center justify-center text-xs text-muted-foreground">
                      image failed
                    </div>
                  )}
                </div>
                <div className="flex items-center justify-between gap-2 px-2.5 py-2">
                  <span className="line-clamp-2 text-[11px] text-muted-foreground">{t.label}</span>
                  <span
                    className={cn(
                      "shrink-0 rounded-full border px-1.5 py-px text-[9.5px] font-semibold",
                      marked
                        ? "border-brand bg-brand-tint text-brand-text"
                        : "border-border text-muted-foreground",
                    )}
                  >
                    {marked ? "re-roll" : t.index === -1 ? "hero" : `#${t.index + 1}`}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <Button
            size="sm"
            variant="outline"
            disabled={busy || locked || selected.size === 0}
            onClick={() =>
              resume({ regenerate: [...selected] }, (anchorId) =>
                logHitlStep(threadId, {
                  icon: "reroll",
                  label: `Re-rolled ${selected.size} image${selected.size === 1 ? "" : "s"}`,
                  anchorId,
                }),
              )
            }
          >
            <RefreshCw className="size-3.5" />
            {selected.size > 0 ? `Regenerate ${selected.size} selected` : "Select shots to re-roll"}
          </Button>
          <Button
            size="sm"
            disabled={busy || locked}
            onClick={() =>
              resume({ approved: true }, (anchorId) =>
                logHitlStep(threadId, { icon: "still", label: "Stills approved", anchorId }),
              )
            }
          >
            <Check className="size-3.5" />
            Approve &amp; finalize post
          </Button>
        </div>
      </div>
    </div>
  );
}
