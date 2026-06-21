"use client";

import { BarChart3 } from "lucide-react";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { AnalyticsDashboardData } from "@/lib/types";

// The generative-UI dashboard the analytics path composes (schemas.py:AnalyticsDashboard). One
// component, two renderers: the useStream UI mounts it via LoadExternalComponent; the CopilotKit
// UI maps it into an A2UI catalog. Props are the dashboard dict verbatim.
export function AnalyticsDashboard({ title, stats = [], table }: AnalyticsDashboardData) {
  if (stats.length === 0 && !table) return null;

  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <BarChart3 className="size-4 text-muted-foreground" />
          {title}
        </CardTitle>
      </CardHeader>

      <CardContent className="space-y-4">
        {stats.length > 0 && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {stats.map((stat, i) => (
              <div key={i} className="rounded-lg border bg-muted/30 p-3">
                <div className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                  {stat.label}
                </div>
                <div className="mt-1 text-lg font-semibold tabular-nums">{stat.value}</div>
                {stat.hint && (
                  <div className="mt-0.5 text-xs text-muted-foreground">{stat.hint}</div>
                )}
              </div>
            ))}
          </div>
        )}

        {table && table.rows.length > 0 && (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full border-collapse text-sm">
              <thead className="bg-muted/50">
                <tr>
                  {table.columns.map((col, i) => (
                    <th key={i} className="border-b px-3 py-2 text-left font-medium">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((row, r) => (
                  <tr key={r}>
                    {row.map((cell, c) => (
                      <td key={c} className="border-b px-3 py-2 tabular-nums">
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
