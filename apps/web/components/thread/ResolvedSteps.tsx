"use client";

import { Check, Diamond, RefreshCw, RotateCcw, X } from "lucide-react";

import { type HitlStep, type HitlStepIcon } from "@/lib/hitl-log";

const ICON: Record<HitlStepIcon, typeof Check> = {
  concept: Diamond,
  approve: Check,
  reject: X,
  regen: RefreshCw,
  still: Check,
  reroll: RotateCcw,
};

// A muted record of the operator's resolved HITL decisions. HITL gates are transient (they vanish on
// resolve, leaving no chat message), so these keep the loop coherent — "◆ Concept …", "✓ Copy approved
// …", "✕ Rejected", "✓ Workspace: 3 actions approved — Create Sheet · …". The parent renders one of
// these INLINE right after the turn each record is anchored to (see thread/index.tsx), so they land in
// order where the card was, not in a flat pile at the bottom. `steps` is already filtered to this turn.
export function ResolvedSteps({ steps }: { steps: HitlStep[] }) {
  if (steps.length === 0) return null;
  return (
    <div className="flex flex-col gap-1 pl-11">
      {steps.map((s) => {
        const Icon = ICON[s.icon];
        return (
          <div
            key={s.id}
            className="flex items-start gap-1.5 text-[11.5px] leading-tight text-muted-foreground"
          >
            <Icon className="mt-[2px] size-3 shrink-0 text-brand/70" />
            <span className="min-w-0">
              {s.label}
              {s.detail ? <span className="text-muted-foreground/70"> — {s.detail}</span> : null}
            </span>
          </div>
        );
      })}
    </div>
  );
}
