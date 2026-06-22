"use client";

import { useState } from "react";
import { Check, Truck } from "lucide-react";
import { toast } from "sonner";

import { RouteMap } from "@/components/operations/RouteMap";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ops } from "@/lib/ops";
import type { RoutePlan } from "@/lib/ops-types";

// The generative-UI route card: the orchestrator's `routing` node push_ui_message("route_map", plan)
// renders here in the chat — the optimizer KPIs + the live OSM map (same RouteMap as /routes) + an
// action-bearing "Dispatch route" button (the Operator endpoint). Props are the RoutePlan dict.
export function RouteMapCard({
  ordered_stops,
  total_km,
  naive_km,
  improvement_pct,
  est_minutes,
  route_id,
  status,
}: RoutePlan) {
  const [currentStatus, setCurrentStatus] = useState(status);
  const [dispatching, setDispatching] = useState(false);
  const dispatched = currentStatus === "dispatched";

  const dispatch = async () => {
    setDispatching(true);
    try {
      const updated = await ops.dispatchRoute(route_id);
      setCurrentStatus(updated.status);
      toast.success("Route dispatched");
    } catch (e) {
      toast.error("Couldn't dispatch route", {
        description: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setDispatching(false);
    }
  };

  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Truck className="size-4 text-muted-foreground" />
          Delivery route · {ordered_stops.length} stops
        </CardTitle>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Kpi label="Optimized" value={`${total_km.toFixed(1)} km`} />
          <Kpi label="Unoptimized" value={`${naive_km.toFixed(1)} km`} />
          <Kpi label="Saved" value={`${improvement_pct.toFixed(0)}%`} tone="success" />
          <Kpi label="Est. time" value={`${Math.round(est_minutes)} min`} />
        </div>

        <RouteMap stops={ordered_stops} />

        <Button
          onClick={dispatch}
          disabled={dispatching || dispatched}
          className="w-full sm:w-auto"
        >
          {dispatched ? (
            <>
              <Check className="size-4" /> Dispatched
            </>
          ) : dispatching ? (
            "Dispatching…"
          ) : (
            <>
              <Truck className="size-4" /> Dispatch route
            </>
          )}
        </Button>
      </CardContent>
    </Card>
  );
}

function Kpi({ label, value, tone }: { label: string; value: string; tone?: "success" }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <div className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{label}</div>
      <div
        className={
          "mt-1 text-lg font-semibold tabular-nums " + (tone === "success" ? "text-emerald-600" : "")
        }
      >
        {value}
      </div>
    </div>
  );
}
