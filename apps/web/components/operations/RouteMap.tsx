"use client";

import type { CSSProperties } from "react";
import dynamic from "next/dynamic";

import type { RouteStop } from "@/lib/ops-types";

// Fixed pin layout for the placeholder (schematic, not geographic) — shown before a route is planned.
const PINS = [
  { top: 78, left: 58 },
  { top: 138, left: 158 },
  { top: 98, left: 238 },
  { top: 188, left: 318 },
  { top: 248, left: 238 },
];

const STRIPES: CSSProperties = {
  background:
    "repeating-linear-gradient(135deg, var(--muted), var(--muted) 9px, var(--border-soft) 9px, var(--border-soft) 18px)",
};

// The real Leaflet/OSM map is client-only (Leaflet touches `window`), so load it with ssr:false and
// fall back to the placeholder while it loads.
const RouteMapLeaflet = dynamic(() => import("./RouteMapLeaflet"), {
  ssr: false,
  loading: () => <RouteMapPlaceholder />,
});

// The Routes map. Real OSM map once a route has stops; the schematic placeholder before then (so the
// screen is never blank and ships with no map call until there's a route to draw).
export function RouteMap({ stops }: { stops: RouteStop[] }) {
  if (stops.length === 0) return <RouteMapPlaceholder />;
  return <RouteMapLeaflet stops={stops} />;
}

// Schematic placeholder — a striped panel, a dashed solver tour and numbered pins.
function RouteMapPlaceholder() {
  return (
    <div className="overflow-hidden rounded-[14px] border bg-card">
      <div className="relative h-[330px]" style={STRIPES}>
        <span className="absolute top-3.5 left-4 rounded-[6px] border bg-card px-2 py-1 font-mono text-[10px] text-muted-foreground">
          Ordered tour · nearest-neighbour + 2-opt
        </span>
        <svg viewBox="0 0 480 330" className="absolute inset-0 h-full w-full">
          <polyline
            points="70,90 170,150 250,110 330,200 250,260 150,230"
            fill="none"
            stroke="var(--ink)"
            strokeWidth={2}
            strokeDasharray="5 5"
            opacity={0.5}
          />
        </svg>
        {PINS.map((p, i) => (
          <span
            key={i}
            className={
              "absolute flex size-[22px] items-center justify-center rounded-full text-[10px] font-semibold " +
              (i === 0 ? "bg-brand text-brand-foreground" : "bg-ink text-ink-foreground")
            }
            style={{ top: p.top, left: p.left }}
          >
            {i + 1}
          </span>
        ))}
      </div>
    </div>
  );
}
