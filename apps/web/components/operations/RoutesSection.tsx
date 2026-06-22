"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { KpiCard } from "@/components/ui/kpi-card";
import { StatusPill } from "@/components/ui/status-pill";
import { ops } from "@/lib/ops";
import type { RoutePlan, RouteStop } from "@/lib/ops-types";
import { cn } from "@/lib/utils";
import { RouteMap } from "./RouteMap";

// Illustrative preview shown before a route is planned (mirrors the hi-fi). Planning replaces these
// with the solver's real ordered stops.
const SAMPLE_STOPS = [
  { seq: 1, city: "Dehiwala", order_id: 1042 },
  { seq: 2, city: "Moratuwa", order_id: 1039 },
  { seq: 3, city: "Panadura", order_id: 1036 },
  { seq: 4, city: "Kalutara", order_id: 1031 },
  { seq: 5, city: "Wadduwa", order_id: 1028 },
];

export function RoutesSection() {
  const [plan, setPlan] = useState<RoutePlan | null>(null);
  const [busy, setBusy] = useState(false);

  const planRoute = async () => {
    setBusy(true);
    try {
      setPlan(await ops.planRoute());
      toast.success("Route planned by the optimizer.");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const dispatch = async () => {
    if (!plan) return;
    setBusy(true);
    try {
      setPlan(await ops.dispatchRoute(plan.route_id));
      toast.success(`Route #${plan.route_id} dispatched — orders shipped.`);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // Real solver output once planned; the design's defaults beforehand so the screen reads complete.
  const optimized = plan?.total_km ?? 41.2;
  const naive = plan?.naive_km ?? 58.6;
  const saved = plan?.improvement_pct ?? 30;
  const estMin = plan?.est_minutes ?? 96;
  const stops: (RouteStop | (typeof SAMPLE_STOPS)[number])[] = plan?.ordered_stops ?? SAMPLE_STOPS;

  return (
    <>
      {/* action row */}
      <div className="flex items-center gap-3">
        <span className="text-[11.5px] text-muted-foreground">
          {plan ? `${plan.ordered_stops.length} stops · ${plan.vehicle}` : "9 stops pending · 1 van"}
        </span>
        <div className="ml-auto">
          {!plan ? (
            <Button className="h-9 rounded-[8px] text-[12.5px]" onClick={planRoute} disabled={busy}>
              {busy ? "Planning…" : "Plan route"}
            </Button>
          ) : plan.status === "dispatched" ? (
            <StatusPill tone="info">Route #{plan.route_id} dispatched</StatusPill>
          ) : (
            <Button className="h-9 rounded-[8px] text-[12.5px]" onClick={dispatch} disabled={busy}>
              {busy ? "Dispatching…" : "Dispatch route →"}
            </Button>
          )}
        </div>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
        <KpiCard label="Optimized" value={`${optimized.toFixed(1)} km`} />
        <KpiCard
          label="Naive"
          value={<span className="text-muted-foreground">{naive.toFixed(1)} km</span>}
        />
        <KpiCard
          label="Saved"
          tone="success"
          value={`${Math.round(saved)}%`}
          sub={`${(naive - optimized).toFixed(1)} km shorter`}
        />
        <KpiCard label="Est. time" value={`${Math.round(estMin)} min`} />
      </div>

      {/* map + stops */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.35fr_1fr]">
        <RouteMap stops={plan?.ordered_stops ?? []} />
        <div className="overflow-hidden rounded-[14px] border bg-card">
          <div className="grid grid-cols-[0.5fr_1fr_1.2fr] border-b bg-panel">
            <HeadCell>#</HeadCell>
            <HeadCell>City</HeadCell>
            <HeadCell>Order</HeadCell>
          </div>
          <div className="divide-y divide-border-soft">
            {stops.map((s) => (
              <div key={s.seq} className="grid grid-cols-[0.5fr_1fr_1.2fr] items-center">
                <div
                  className={cn(
                    "px-3.5 py-[11px] font-mono text-[12.5px] tabular-nums",
                    s.seq === 1 && "font-semibold text-brand-text",
                  )}
                >
                  {s.seq}
                </div>
                <div className="px-3.5 py-[11px] text-[12.5px]">{s.city}</div>
                <div className="px-3.5 py-[11px] font-mono text-[11.5px] text-muted-foreground tabular-nums">
                  #{s.order_id}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

function HeadCell({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-3.5 py-[11px] font-mono text-[9.5px] tracking-[0.06em] text-muted-foreground uppercase">
      {children}
    </div>
  );
}
