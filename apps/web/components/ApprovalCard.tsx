"use client";

import { useState } from "react";
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
    <div className="card">
      <h3>⏸ Human review</h3>
      <div className="sub">{payload.question}</div>

      {beats.map((beat, i) => (
        <div className="beat" key={i}>
          <div className="t">
            {beat.t_start_s}s – {beat.t_end_s}s
          </div>
          {editing ? (
            <textarea
              rows={2}
              value={beat.voiceover}
              onChange={(e) => setVoiceover(i, e.target.value)}
            />
          ) : (
            <div>{beat.voiceover}</div>
          )}
        </div>
      ))}

      <div className="row">
        {editing ? (
          <button
            className="btn approve"
            disabled={disabled}
            onClick={() => onDecision({ approved: true, edited_script: beats })}
          >
            Save &amp; approve
          </button>
        ) : (
          <button className="btn approve" disabled={disabled} onClick={() => onDecision({ approved: true })}>
            Approve
          </button>
        )}
        <button className="btn edit" disabled={disabled} onClick={() => setEditing((e) => !e)}>
          {editing ? "Cancel edit" : "Edit script"}
        </button>
        <button className="btn reject" disabled={disabled} onClick={() => onDecision({ approved: false })}>
          Reject
        </button>
      </div>
    </div>
  );
}
