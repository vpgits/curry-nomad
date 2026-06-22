"use client";

import { BarChart3 } from "lucide-react";
import type { Message } from "@langchain/langgraph-sdk";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { AnalyticsDashboardData, DashboardChart } from "@/lib/types";
import { useStreamContext } from "@/providers/Stream";

// Warm turmeric/earth palette, in step with the Operator redesign.
const CHART_COLORS = ["#d97706", "#0f766e", "#b45309", "#7c3aed", "#0369a1", "#be123c"];

// The generative-UI dashboard the analytics path composes (schemas.py:AnalyticsDashboard). The
// useStream UI mounts it via LoadExternalComponent. Props are the dashboard dict verbatim.
export function AnalyticsDashboard({ title, stats = [], table, chart }: AnalyticsDashboardData) {
  const stream = useStreamContext();
  const hasChart =
    !!chart && chart.kind !== "none" && Array.isArray(chart.series) && chart.series.length > 0;
  if (stats.length === 0 && !table && !hasChart) return null;

  // Drill-down: a table row click asks the agent to break that row down further. The component is
  // mounted inside the StreamProvider tree (via LoadExternalComponent's local component map), so it
  // can submit a fresh human turn just like the composer does (thread/index.tsx:send).
  const drillInto = (label: string) => {
    const content = `Break down "${label}" further.`;
    stream.submit(
      { messages: [{ type: "human", content }] },
      {
        streamMode: ["values"],
        streamSubgraphs: true,
        optimisticValues: (prev) => ({
          ...prev,
          messages: [
            ...(prev.messages ?? []),
            { type: "human", content, id: `tmp-${crypto.randomUUID()}` } as Message,
          ],
        }),
      },
    );
  };

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

        {hasChart && <DashboardChartView chart={chart!} />}

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

// The chart the builder model chose (bar/line/pie). A thin Recharts wrapper — the model decides the
// kind, this just draws it.
function DashboardChartView({ chart }: { chart: DashboardChart }) {
  return (
    <div className="rounded-lg border bg-muted/20 p-3">
      <div className="h-[210px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          {chart.kind === "pie" ? (
            <PieChart>
              <Tooltip />
              <Pie
                data={chart.series}
                dataKey="value"
                nameKey="label"
                cx="50%"
                cy="50%"
                innerRadius={45}
                outerRadius={85}
                paddingAngle={2}
              >
                {chart.series.map((_, i) => (
                  <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                ))}
              </Pie>
            </PieChart>
          ) : chart.kind === "line" ? (
            <LineChart data={chart.series} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Line
                type="monotone"
                dataKey="value"
                stroke={CHART_COLORS[0]}
                strokeWidth={2}
                dot={{ r: 3 }}
              />
            </LineChart>
          ) : (
            <BarChart data={chart.series} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {chart.series.map((_, i) => (
                  <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
      {(chart.x_label || chart.y_label) && (
        <div className="mt-1 flex justify-between px-1 text-[10px] text-muted-foreground">
          <span>{chart.x_label}</span>
          <span>{chart.y_label}</span>
        </div>
      )}
    </div>
  );
}
