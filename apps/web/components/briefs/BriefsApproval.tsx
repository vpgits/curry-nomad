"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQueryState } from "nuqs";

import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/typography";
import { Textarea } from "@/components/ui/textarea";
import type { MarketingInterrupt, ReviewDecision, ReviewInterrupt, ScriptBeat } from "@/lib/types";
import { useStreamContext } from "@/providers/Stream";
import { cn } from "@/lib/utils";

// The relocated HITL approval gate. Reads the paused marketing run from the hoisted stream and
// resumes it with the operator's decision — then routes to /ask so the resumed run streams in the
// chat. Keeps ApprovalCard's edit-in-place logic; only the surface + IA changed.
//
// Outer/inner split: keying the inner on the proposed script means a *revised* draft remounts it
// (re-seeding local edit state from props) without a reset effect.
export function BriefsApproval() {
  const stream = useStreamContext();
  const interrupt = stream.interrupt?.value as MarketingInterrupt | undefined;

  // Only the script-review gate is reviewed here; the concept-pick gate is an inline selection on
  // /ask, so treat it as "nothing awaiting review".
  if (!interrupt || interrupt.kind === "concept_pick") {
    return (
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 bg-body-bg p-10 text-center">
        <div className="text-base font-semibold">No briefs awaiting review</div>
        <p className="max-w-sm text-sm text-muted-foreground">
          When the marketing workflow drafts an ad, it pauses here for your approval before spending
          compute on the storyboard.
        </p>
        <Link
          href="/ask"
          className="mt-1 rounded-[8px] bg-ink px-4 py-2 text-[13px] font-medium text-ink-foreground"
        >
          ✦ Ask Nora to make an ad
        </Link>
      </div>
    );
  }

  return <Review key={JSON.stringify(interrupt.script_beats)} interrupt={interrupt} />;
}

function Review({ interrupt }: { interrupt: ReviewInterrupt }) {
  const stream = useStreamContext();
  const router = useRouter();
  const [threadId] = useQueryState("threadId");
  const isLoading = stream.isLoading;

  const [editing, setEditing] = useState(false);
  const [beats, setBeats] = useState<ScriptBeat[]>(interrupt.script_beats ?? []);

  const setVoiceover = (i: number, value: string) =>
    setBeats((prev) => prev.map((b, j) => (j === i ? { ...b, voiceover: value } : b)));

  const decide = (decision: ReviewDecision) => {
    stream.submit(undefined, {
      command: { resume: decision },
      streamMode: ["values"],
      streamSubgraphs: true,
    });
    // The stream lives in the root layout, so it keeps running across this navigation — land on
    // /ask to watch the storyboard + prompts stream in.
    router.push(threadId ? `/ask?threadId=${threadId}` : "/ask");
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* paused banner */}
      <div className="flex shrink-0 items-center gap-3 border-b border-brand-edge bg-brand-tint/40 px-[26px] py-3">
        <span className="size-2.5 rounded-full bg-brand" />
        <div className="text-[13.5px] font-semibold text-brand-text">
          Workflow paused — awaiting your review
        </div>
        <span className="ml-auto font-mono text-[10.5px] text-brand-text">~30s script · review</span>
      </div>

      {/* two-pane body */}
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[1.35fr_1fr]">
        {/* left — proposed script */}
        <div className="overflow-y-auto border-r px-[26px] py-5">
          <div className="text-sm font-semibold">Proposed script</div>
          <div className="mb-4 text-[11.5px] text-muted-foreground">
            {editing
              ? "Edit any beat below, then approve to continue the workflow."
              : "Review the beats, then approve — or edit before approving."}
          </div>
          <div className="flex flex-col gap-3">
            {beats.map((beat, i) => (
              <div
                key={beat.t_start_s}
                className={cn(
                  "pl-3.5",
                  editing
                    ? "rounded-r-[8px] border-l-2 border-brand bg-brand-tint/30 py-1"
                    : "border-l-2 border-ink py-0.5",
                )}
              >
                <div
                  className={cn(
                    "font-mono text-[10.5px]",
                    editing ? "text-brand-text" : "text-muted-foreground",
                  )}
                >
                  {beat.t_start_s}s – {beat.t_end_s}s{editing && " · editing"}
                </div>
                {editing ? (
                  <Textarea
                    rows={2}
                    value={beat.voiceover}
                    onChange={(e) => setVoiceover(i, e.target.value)}
                    className="mt-1.5 resize-y border-brand-edge bg-card text-[13.5px]"
                  />
                ) : (
                  <p className="mt-1 text-[13.5px] leading-[1.55]">{beat.voiceover}</p>
                )}
                {beat.on_screen_text && !editing && (
                  <p className="mt-1 text-[11.5px] text-muted-foreground">
                    On-screen: {beat.on_screen_text}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* right — context */}
        <div className="flex flex-col gap-[18px] overflow-y-auto bg-body-bg px-6 py-5">
          <div>
            <Eyebrow className="mb-2.5 text-[9.5px]">Why you&apos;re reviewing</Eyebrow>
            <p className="text-[13px] leading-[1.55]">{interrupt.question}</p>
          </div>
          <div>
            <Eyebrow className="mb-2.5 text-[9.5px]">After you approve</Eyebrow>
            <p className="text-[12.5px] leading-[1.55] text-muted-foreground">
              Nora builds the storyboard, per-shot video prompts, music mood and hashtags — all
              grounded in real product data. Rejecting skips that compute entirely.
            </p>
          </div>
        </div>
      </div>

      {/* sticky action bar */}
      <div className="flex shrink-0 items-center gap-3 border-t bg-background px-[26px] py-3.5">
        <Button
          disabled={isLoading}
          className="rounded-[8px]"
          onClick={() =>
            decide(editing ? { approved: true, edited_script: beats } : { approved: true })
          }
        >
          ✓ Approve &amp; continue
        </Button>
        <Button
          variant="outline"
          disabled={isLoading}
          className="rounded-[8px]"
          onClick={() => setEditing((e) => !e)}
        >
          ✎ {editing ? "Cancel edit" : "Edit script"}
        </Button>
        <Button
          variant="outline"
          disabled={isLoading}
          className="rounded-[8px] border-danger-edge text-danger-text hover:bg-danger-tint/40"
          onClick={() => decide({ approved: false })}
        >
          ✕ Reject
        </Button>
        <span className="ml-auto font-mono text-[10.5px] text-muted-foreground">
          Resumes the paused run
        </span>
      </div>
    </div>
  );
}
