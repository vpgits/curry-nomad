"use client";

import dynamic from "next/dynamic";
import { Sparkles } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { A2uiBlock, A2uiMetric } from "@/lib/types";

const TREND_COLOR: Record<string, string> = {
  up: "#059669",
  down: "#dc2626",
  neutral: "var(--muted-foreground)",
};
const TREND_GLYPH: Record<string, string> = { up: "↑", down: "↓", neutral: "→" };

const EMPTY_BLOCKS: A2uiBlock[] = [];

// The recharts chart block is split into its own client-only chunk and next/dynamic-imported with
// ssr:false (recharts is heavy and only renders below the fold, after a chat turn) — mirrors the
// RouteMap → RouteMapLeaflet split.
const ChartView = dynamic(() => import("./A2uiChartView"), { ssr: false });

// Renders an LLM-authored A2UI surface (schemas.py:A2uiSurface) — the model composed this ordered
// block list, this just maps each block to a catalog renderer. The "LLM authors the UI" half of
// the generative-UI showcase (the fixed AnalyticsDashboard is the other half).
export function A2uiSurfaceView({ blocks = EMPTY_BLOCKS }: { blocks: A2uiBlock[] }) {
  if (!blocks.length) return null;
  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        {blocks.map((block, i) => (
          <Block key={i} block={block} />
        ))}
      </CardContent>
    </Card>
  );
}

function Block({ block }: { block: A2uiBlock }) {
  switch (block.type) {
    case "heading":
      return (
        <h3 className="flex items-center gap-2 text-base font-semibold tracking-tight">
          <Sparkles className="size-4 shrink-0 text-brand" />
          {block.text}
        </h3>
      );
    case "text":
      return <p className="text-sm leading-relaxed text-muted-foreground">{block.text}</p>;
    case "metrics":
      return <MetricsRow items={block.metrics ?? []} />;
    case "chart":
      return (
        <ChartView
          title={block.title ?? ""}
          kind={block.chart_kind ?? "bar"}
          series={block.series ?? []}
        />
      );
    case "table":
      return <TableView columns={block.columns ?? []} rows={block.rows ?? []} />;
    default:
      return null;
  }
}

function MetricsRow({ items }: { items: A2uiMetric[] }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {items.map((m) => (
        <div key={m.label} className="rounded-lg border bg-muted/30 p-3">
          <div className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            {m.label}
          </div>
          <div className="mt-1 flex items-baseline gap-1.5">
            <span className="text-lg font-semibold tabular-nums">{m.value}</span>
            {m.trend && (
              <span
                className="text-xs font-medium"
                style={{ color: TREND_COLOR[m.trend] ?? "var(--muted-foreground)" }}
              >
                {TREND_GLYPH[m.trend]}
                {m.trend_value ? ` ${m.trend_value}` : ""}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function TableView({ columns, rows }: { columns: string[]; rows: string[][] }) {
  if (rows.length === 0) return null;
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full border-collapse text-sm">
        <thead className="bg-muted/50">
          <tr>
            {columns.map((col) => (
              <th key={col} className="border-b px-3 py-2 text-left font-medium">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
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
  );
}
