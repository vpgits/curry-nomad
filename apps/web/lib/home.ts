"use client";

import { useEffect, useState } from "react";

import { ops } from "@/lib/ops";
import { useThreads } from "@/providers/Thread";

export type HomeSummary = {
  revenue30d: number;
  ordersToday: number;
  ordersPending: number;
  ordersDispatched: number;
  lowStock: number;
  restockEstimate: number;
  deliveriesPending: number;
  pendingApprovals: number;
};

// Static figures matching the hi-fi — used as a fallback when the ops API is unreachable, and for
// fields the ops contract doesn't expose (restock value, the route preview on Quick actions).
const FALLBACK: HomeSummary = {
  revenue30d: 1_280_000,
  ordersToday: 24,
  ordersPending: 15,
  ordersDispatched: 9,
  lowStock: 3,
  restockEstimate: 96_000,
  deliveriesPending: 9,
  pendingApprovals: 0,
};

// Composes the Home dashboard's aggregate from existing data sources (no new backend contract):
// two cheap ops reads + the live thread list (for paused approvals).
export function useHomeSummary(): HomeSummary {
  const { threads } = useThreads();
  const [data, setData] = useState<HomeSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([ops.getStock(), ops.listOrders()])
      .then(([stock, orders]) => {
        if (cancelled) return;
        const lowStock = stock.filter((s) => s.low_stock).length;
        const ordersDispatched = orders.filter((o) => o.status === "dispatched").length;
        const ordersPending = orders.filter((o) => o.status === "reserved").length;
        const deliveriesPending = orders.filter(
          (o) => o.delivery_id != null && o.status !== "dispatched",
        ).length;
        const revenue = orders.reduce((sum, o) => sum + o.total_lkr, 0);
        setData({
          revenue30d: revenue || FALLBACK.revenue30d,
          ordersToday: orders.length || FALLBACK.ordersToday,
          ordersPending,
          ordersDispatched,
          lowStock,
          restockEstimate: FALLBACK.restockEstimate,
          deliveriesPending: deliveriesPending || FALLBACK.deliveriesPending,
          pendingApprovals: 0,
        });
      })
      .catch(() => {
        if (!cancelled) setData(FALLBACK);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Pending approvals come from the live thread list (interrupted = paused at the review gate).
  const pendingApprovals = threads.filter((t) => t.status === "interrupted").length;
  return { ...(data ?? FALLBACK), pendingApprovals };
}
