"use client";

import { Clapperboard } from "lucide-react";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { Shot, ShotPrompt } from "@/lib/types";

// Stable empty defaults so re-renders reuse one reference (inline [] would allocate fresh each
// time, breaking referential equality for memoized children / dependency arrays).
const EMPTY_SHOTS: Shot[] = [];
const EMPTY_SHOT_PROMPTS: ShotPrompt[] = [];

// The storyboard the marketing workflow produced, as a horizontal filmstrip of shot cards. Each
// shot is paired (by index) with its text-to-video prompt — info the brief card only summarises as
// a count. Pushed via push_ui_message("marketing_storyboard", { shots, shot_prompts }).
export function StoryboardFilmstrip({
  shots = EMPTY_SHOTS,
  shot_prompts = EMPTY_SHOT_PROMPTS,
}: {
  shots: Shot[];
  shot_prompts: ShotPrompt[];
}) {
  if (shots.length === 0) return null;
  const promptFor = (index: number) =>
    shot_prompts.find((p) => p.index === index)?.t2v_prompt ?? "";

  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Clapperboard className="size-4 text-muted-foreground" />
          Storyboard · {shots.length} shots
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex gap-3 overflow-x-auto pb-2">
          {shots.map((shot) => (
            <figure
              key={shot.index}
              className="flex w-56 shrink-0 flex-col gap-2 rounded-lg border bg-muted/30 p-3"
            >
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span className="font-mono font-medium text-foreground/80">
                  Shot {shot.index + 1}
                </span>
                <span className="tabular-nums">{shot.duration_s}s</span>
              </div>
              <div className="aspect-video rounded-md border border-dashed bg-gradient-to-br from-muted to-accent/30" />
              <p className="text-[13px] leading-snug">{shot.scene_description}</p>
              {promptFor(shot.index) && (
                <figcaption className="border-t pt-2 font-mono text-[10.5px] leading-snug text-muted-foreground">
                  {promptFor(shot.index)}
                </figcaption>
              )}
            </figure>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
