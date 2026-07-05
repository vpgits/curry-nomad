"use client";

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

import type { DashboardChart } from "@/lib/types";

// Warm turmeric/earth palette, in step with the Operator redesign.
const CHART_COLORS = ["#d97706", "#0f766e", "#b45309", "#7c3aed", "#0369a1", "#be123c"];

// The chart the builder model chose (bar/line/pie). A thin Recharts wrapper — the model decides the
// kind, this just draws it. Default export so AnalyticsDashboard can next/dynamic-import it with
// ssr:false (recharts is heavy and only renders below the fold, after a chat turn).
export default function AnalyticsDashboardChart({ chart }: { chart: DashboardChart }) {
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
                {chart.series.map((point, i) => (
                  <Cell key={point.label} fill={CHART_COLORS[i % CHART_COLORS.length]} />
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
                {chart.series.map((point, i) => (
                  <Cell key={point.label} fill={CHART_COLORS[i % CHART_COLORS.length]} />
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
