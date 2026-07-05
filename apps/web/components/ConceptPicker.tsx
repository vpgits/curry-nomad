"use client";

import { Lightbulb, Quote } from "lucide-react";
import { useQueryState } from "nuqs";

import { NoraAvatar } from "@/components/thread/messages/ai";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { ConceptPickInterrupt } from "@/lib/types";
import { buildSubmitConfig } from "@/lib/run-config";
import { logHitlStep } from "@/lib/hitl-log";
import { useSubmitLock } from "@/lib/use-submit-lock";
import { useStreamContext } from "@/providers/Stream";

// The interactive concept-pick gate: the marketing workflow's parallel ideation, surfaced as
// selectable cards. Choosing one resumes the paused run with that index (Command(resume=...)) on
// the same thread — the interrupt/resume HITL pattern, but as a real selection rather than an
// approve/reject. Rendered inline in the thread when stream.interrupt.value.kind === "concept_pick".
export function ConceptPicker({ interrupt }: { interrupt: ConceptPickInterrupt }) {
  const stream = useStreamContext();
  const busy = stream.isLoading;
  const [locked, runLocked] = useSubmitLock();
  const [threadId] = useQueryState("threadId");

  // Carry the run config (Google token + Author-UI mode) on resume: run config is NOT persisted across
  // an interrupt, so a marketing→workspace chain resumed from here would otherwise reach the workspace
  // node tokenless and stub out. The lock blocks a double-fire during the token fetch. Then record the
  // pick so it stays in the conversation loop after the gate clears.
  const choose = (chosen_index: number) =>
    runLocked(async () => {
      const runConfig = await buildSubmitConfig();
      // Anchor to the message this pick followed so the record renders inline at the right turn.
      const anchorId = stream.messages[stream.messages.length - 1]?.id;
      stream.submit(undefined, {
        command: { resume: { chosen_index } },
        streamMode: ["values"],
        streamSubgraphs: true,
        ...runConfig,
      });
      logHitlStep(threadId, {
        icon: "concept",
        label: `Concept: ${interrupt.concepts[chosen_index]?.angle ?? `#${chosen_index + 1}`}`,
        anchorId,
      });
    });

  return (
    <div className="flex items-start gap-3">
      <NoraAvatar />
      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold">Nora</span>
          <span className="rounded-full border border-brand-edge bg-brand-tint px-2 py-px text-[9.5px] font-semibold text-brand-text">
            Marketing workflow
          </span>
        </div>
        <p className="text-[13.5px] text-muted-foreground">{interrupt.question}</p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {interrupt.concepts.map((c, i) => (
            <Card key={c.angle} className="flex flex-col gap-3">
              <CardHeader>
                <CardTitle className="flex items-start gap-2 text-sm leading-snug">
                  <Lightbulb className="mt-0.5 size-4 shrink-0 text-brand" />
                  {c.angle}
                </CardTitle>
              </CardHeader>
              <CardContent className="flex-1 space-y-2">
                <p className="flex gap-1.5 text-[13px] leading-relaxed">
                  <Quote className="mt-0.5 size-3 shrink-0 text-muted-foreground" />
                  <span className="italic">{c.hook}</span>
                </p>
                <p className="text-xs text-muted-foreground">{c.rationale}</p>
              </CardContent>
              <CardFooter>
                <Button
                  size="sm"
                  className="w-full"
                  disabled={busy || locked}
                  onClick={() => choose(i)}
                >
                  Develop this concept
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}
