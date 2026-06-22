"use client";

import { CircleCheck, CircleX, Lightbulb, TriangleAlert } from "lucide-react";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { Critique } from "@/lib/types";

// The evaluator's verdict from the evaluator-optimizer loop (schemas.py:Critique). Surfacing it
// makes the critique → revise loop visible — it's not in the brief card. Pushed via
// push_ui_message("marketing_critique", critique).
export function CritiqueCard({
  passed = false,
  issues = [],
  suggestions = [],
}: Critique) {
  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          {passed ? (
            <CircleCheck className="size-4 text-emerald-600" />
          ) : (
            <CircleX className="size-4 text-amber-600" />
          )}
          Critique · {passed ? "passed" : "revised"}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {issues.length > 0 && (
          <Section
            icon={<TriangleAlert className="size-3.5 text-amber-600" />}
            title="Issues"
            items={issues}
          />
        )}
        {suggestions.length > 0 && (
          <Section
            icon={<Lightbulb className="size-3.5 text-muted-foreground" />}
            title="Suggestions"
            items={suggestions}
          />
        )}
        {issues.length === 0 && suggestions.length === 0 && (
          <p className="text-sm text-muted-foreground">No notes — the draft passed cleanly.</p>
        )}
      </CardContent>
    </Card>
  );
}

function Section({
  icon,
  title,
  items,
}: {
  icon: React.ReactNode;
  title: string;
  items: string[];
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5 text-xs font-medium tracking-wide text-muted-foreground uppercase">
        {icon}
        {title}
      </div>
      <ul className="space-y-1">
        {items.map((it, i) => (
          <li key={i} className="flex gap-2 text-sm leading-relaxed">
            <span className="text-muted-foreground">·</span>
            {it}
          </li>
        ))}
      </ul>
    </div>
  );
}
