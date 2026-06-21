"use client";

import { useState } from "react";
import { Route, Truck } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ops } from "@/lib/ops";
import type { RoutePlan } from "@/lib/ops-types";

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <div className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

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

  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle className="flex items-center justify-between text-base">
          <span>Delivery routing</span>
          {!plan && (
            <Button size="xs" onClick={planRoute} disabled={busy}>
              <Route /> {busy ? "Planning…" : "Plan route"}
            </Button>
          )}
        </CardTitle>
      </CardHeader>

      <CardContent className="space-y-4">
        {!plan ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Plan a route over the pending deliveries. A deterministic solver (nearest-neighbor +
            2-opt) orders the stops — the part a language model can&apos;t reliably do.
          </p>
        ) : (
          <>
            {/* The teaching payoff: the solver vs the unplanned "visit them as listed" baseline. */}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label="Optimized" value={`${plan.total_km.toFixed(1)} km`} hint="solver tour" />
              <Stat
                label="Naive"
                value={`${plan.naive_km.toFixed(1)} km`}
                hint="visit as listed"
              />
              <Stat
                label="Saved"
                value={`${plan.improvement_pct.toFixed(0)}%`}
                hint={`${(plan.naive_km - plan.total_km).toFixed(1)} km shorter`}
              />
              <Stat label="Est. time" value={`${Math.round(plan.est_minutes)} min`} hint={plan.vehicle} />
            </div>

            <div className="flex items-center justify-between">
              <Badge variant={plan.status === "dispatched" ? "secondary" : "default"}>
                Route #{plan.route_id} · {plan.status}
              </Badge>
              {plan.status === "planned" && (
                <Button size="sm" onClick={dispatch} disabled={busy}>
                  <Truck /> {busy ? "Dispatching…" : "Dispatch route"}
                </Button>
              )}
            </div>

            <div className="overflow-x-auto rounded-lg border">
              <table className="w-full border-collapse text-sm">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="border-b px-3 py-2 text-left font-medium">Stop</th>
                    <th className="border-b px-3 py-2 text-left font-medium">Order</th>
                    <th className="border-b px-3 py-2 text-left font-medium">City</th>
                    <th className="border-b px-3 py-2 text-left font-medium">Address</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.ordered_stops.map((s) => (
                    <tr key={s.delivery_id} className="hover:bg-muted/30">
                      <td className="border-b px-3 py-2 tabular-nums">{s.seq}</td>
                      <td className="border-b px-3 py-2 tabular-nums">#{s.order_id}</td>
                      <td className="border-b px-3 py-2">{s.city}</td>
                      <td className="border-b px-3 py-2 text-muted-foreground">{s.address}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
