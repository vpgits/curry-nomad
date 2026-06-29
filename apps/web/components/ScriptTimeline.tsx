"use client";

import { Film } from "lucide-react";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { ScriptBeat } from "@/lib/types";

const SEGMENT_COLORS = ["#d97706", "#0f766e", "#b45309", "#7c3aed", "#0369a1", "#be123c"];

// Stable empty default so re-renders reuse one reference (an inline [] allocates fresh each time).
const EMPTY_BEATS: ScriptBeat[] = [];

// The approved script as a proportional time axis (beats sized by their duration) plus the
// voiceover per beat — a more legible view of the same beats the brief lists. Pushed via
// push_ui_message("marketing_script_timeline", { script_beats }).
export function ScriptTimeline({ script_beats = EMPTY_BEATS }: { script_beats: ScriptBeat[] }) {
  if (script_beats.length === 0) return null;
  const total = Math.max(...script_beats.map((b) => b.t_end_s), 1);

  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Film className="size-4 text-muted-foreground" />
          Script · ~{Math.round(total)}s
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* proportional axis — each segment's width tracks its on-screen duration */}
        <div className="flex h-2.5 w-full overflow-hidden rounded-full">
          {script_beats.map((b, i) => (
            <div
              key={b.t_start_s}
              title={`${b.t_start_s}s – ${b.t_end_s}s`}
              style={{
                width: `${((b.t_end_s - b.t_start_s) / total) * 100}%`,
                backgroundColor: SEGMENT_COLORS[i % SEGMENT_COLORS.length],
              }}
            />
          ))}
        </div>

        <ol className="space-y-2.5">
          {script_beats.map((b, i) => (
            <li key={b.t_start_s} className="flex gap-3">
              <span
                className="mt-1 size-2.5 shrink-0 rounded-full"
                style={{ backgroundColor: SEGMENT_COLORS[i % SEGMENT_COLORS.length] }}
              />
              <div className="min-w-0 flex-1">
                <div className="font-mono text-xs text-muted-foreground">
                  {b.t_start_s}s – {b.t_end_s}s
                </div>
                <p className="text-sm leading-relaxed">{b.voiceover}</p>
                {b.on_screen_text && (
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    on-screen: <span className="font-medium">{b.on_screen_text}</span>
                  </p>
                )}
              </div>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
