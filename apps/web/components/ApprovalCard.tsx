"use client";

import { useState } from "react";
import { Check, Pencil, PauseCircle, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import type { ReviewDecision, ReviewInterrupt, ScriptBeat } from "@/lib/types";

// The HITL gate. Renders the proposed ~30s script and lets the operator approve, edit, or
// reject before the workflow spends compute on the storyboard + per-shot prompts.
export function ApprovalCard({
  payload,
  disabled,
  onDecision,
}: {
  payload: ReviewInterrupt;
  disabled: boolean;
  onDecision: (decision: ReviewDecision) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [beats, setBeats] = useState<ScriptBeat[]>(payload.script_beats ?? []);

  const setVoiceover = (i: number, value: string) =>
    setBeats((prev) => prev.map((b, j) => (j === i ? { ...b, voiceover: value } : b)));

  return (
    <Card className="border-primary/30 ring-primary/10">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <PauseCircle className="size-4 text-muted-foreground" />
          Human review
        </CardTitle>
        <CardAction>
          <Badge variant="secondary">Action needed</Badge>
        </CardAction>
        <CardDescription>{payload.question}</CardDescription>
      </CardHeader>

      <CardContent className="space-y-3">
        {beats.map((beat, i) => (
          <div key={i} className="border-l-2 border-border pl-3">
            <div className="mb-1 font-mono text-xs text-muted-foreground">
              {beat.t_start_s}s – {beat.t_end_s}s
            </div>
            {editing ? (
              <Textarea
                rows={2}
                value={beat.voiceover}
                onChange={(e) => setVoiceover(i, e.target.value)}
                className="resize-y"
              />
            ) : (
              <p className="text-sm leading-relaxed">{beat.voiceover}</p>
            )}
          </div>
        ))}
      </CardContent>

      <CardFooter className="flex-wrap gap-2">
        {editing ? (
          <Button
            disabled={disabled}
            onClick={() => onDecision({ approved: true, edited_script: beats })}
          >
            <Check /> Save &amp; approve
          </Button>
        ) : (
          <Button disabled={disabled} onClick={() => onDecision({ approved: true })}>
            <Check /> Approve
          </Button>
        )}
        <Button
          variant="outline"
          disabled={disabled}
          onClick={() => setEditing((e) => !e)}
        >
          <Pencil /> {editing ? "Cancel edit" : "Edit script"}
        </Button>
        <Button
          variant="destructive"
          disabled={disabled}
          onClick={() => onDecision({ approved: false })}
        >
          <X /> Reject
        </Button>
      </CardFooter>
    </Card>
  );
}
