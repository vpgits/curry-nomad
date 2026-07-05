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

import type { ChartPoint } from "@/lib/types";

const CHART_COLORS = ["#d97706", "#0f766e", "#b45309", "#7c3aed", "#0369a1", "#be123c"];

// One A2UI chart block (bar/line/pie). Default export so A2uiSurfaceView can next/dynamic-import it
// with ssr:false — recharts is heavy and these cards only render below the fold, after a chat turn.
export default function A2uiChartView({
  title,
  kind,
  series,
}: {
  title: string;
  kind: "bar" | "line" | "pie";
  series: ChartPoint[];
}) {
  if (series.length === 0) return null;
  return (
    <div className="rounded-lg border bg-muted/20 p-3">
      {title && <div className="mb-2 text-sm font-medium">{title}</div>}
      <div className="h-[210px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          {kind === "pie" ? (
            <PieChart>
              <Tooltip />
              <Pie
                data={series}
                dataKey="value"
                nameKey="label"
                cx="50%"
                cy="50%"
                innerRadius={45}
                outerRadius={85}
                paddingAngle={2}
              >
                {series.map((point, i) => (
                  <Cell key={point.label} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                ))}
              </Pie>
            </PieChart>
          ) : kind === "line" ? (
            <LineChart data={series} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
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
            <BarChart data={series} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {series.map((point, i) => (
                  <Cell key={point.label} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
