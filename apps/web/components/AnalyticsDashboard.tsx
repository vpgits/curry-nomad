"use client";

import dynamic from "next/dynamic";
import { BarChart3 } from "lucide-react";
import type { Message } from "@langchain/langgraph-sdk";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { AnalyticsDashboardData, DashboardStat } from "@/lib/types";
import { buildSubmitConfig } from "@/lib/run-config";
import { useSubmitLock } from "@/lib/use-submit-lock";
import { useStreamContext } from "@/providers/Stream";

const EMPTY_STATS: DashboardStat[] = [];

// The recharts chart is split into its own client-only chunk and next/dynamic-imported with
// ssr:false (recharts is heavy and only renders below the fold, after a chat turn) — mirrors the
// RouteMap → RouteMapLeaflet split.
const DashboardChartView = dynamic(() => import("./AnalyticsDashboardChart"), { ssr: false });

// The generative-UI dashboard the analytics path composes (schemas.py:AnalyticsDashboard). The
// useStream UI mounts it via LoadExternalComponent. Props are the dashboard dict verbatim.
export function AnalyticsDashboard({
  title,
  stats = EMPTY_STATS,
  table,
  chart,
}: AnalyticsDashboardData) {
  const stream = useStreamContext();
  const [, runLocked] = useSubmitLock();
  const hasChart =
    !!chart && chart.kind !== "none" && Array.isArray(chart.series) && chart.series.length > 0;
  if (stats.length === 0 && !table && !hasChart) return null;

  // Drill-down: a table row click asks the agent to break that row down further. The component is
  // mounted inside the StreamProvider tree (via LoadExternalComponent's local component map), so it
  // can submit a fresh human turn just like the composer does (thread/index.tsx:send) — including the
  // shared run config (Author-UI mode / Google token), which a drill-down previously dropped so the
  // Author-UI toggle silently reverted to the fixed dashboard. The lock blocks a same-click re-fire.
  const drillInto = (label: string) =>
    runLocked(async () => {
      const content = `Break down "${label}" further.`;
      const runConfig = await buildSubmitConfig();
      stream.submit(
        { messages: [{ type: "human", content }] },
        {
          streamMode: ["values"],
          streamSubgraphs: true,
          ...runConfig,
          optimisticValues: (prev) => ({
            ...prev,
            messages: [
              ...(prev.messages ?? []),
              { type: "human", content, id: `tmp-${crypto.randomUUID()}` } as Message,
            ],
          }),
        },
      );
    });

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
            {stats.map((stat) => (
              <div key={stat.label} className="rounded-lg border bg-muted/30 p-3">
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

        {hasChart && <DashboardChartView chart={chart!} />}

        {table && table.rows.length > 0 && (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full border-collapse text-sm">
              <thead className="bg-muted/50">
                <tr>
                  {table.columns.map((col) => (
                    <th key={col} className="border-b px-3 py-2 text-left font-medium">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((row, r) => (
                  <tr
                    key={r}
                    onClick={() => drillInto(row[0])}
                    title={`Break down "${row[0]}" further`}
                    className="cursor-pointer transition-colors hover:bg-accent/40"
                  >
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
