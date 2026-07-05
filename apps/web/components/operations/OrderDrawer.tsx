"use client";

import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/typography";
import { StatusPill } from "@/components/ui/status-pill";
import { formatRupees, type Order } from "@/lib/ops-types";
import { orderStatusLabel, orderStatusTone } from "./order-status";

function timeOf(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

// The order detail panel — used inline (desktop, 316px) and inside a Sheet (mobile).
export function OrderDrawer({ order, onMarkPacked }: { order: Order; onMarkPacked: () => void }) {
  const placed = timeOf(order.created_at);
  return (
    <div className="flex flex-col gap-4 px-[22px] py-5">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold">Order #{order.order_id}</div>
        <StatusPill tone={orderStatusTone(order.status)} className="text-[10px]">
          {orderStatusLabel(order.status)}
        </StatusPill>
      </div>
      <div className="-mt-2 text-[11.5px] text-muted-foreground">
        {order.customer_name}
        {placed && ` · placed ${placed}`}
      </div>

      <div>
        <Eyebrow className="mb-2.5 text-[9.5px]">Line items</Eyebrow>
        <div className="flex flex-col gap-2.5">
          {order.items.map((it) => (
            <div key={it.product_id} className="flex justify-between gap-3 text-[12.5px]">
              <span className="min-w-0 truncate">
                {it.name} <span className="text-muted-foreground">×{it.quantity}</span>
              </span>
              <span className="shrink-0 font-mono tabular-nums">{formatRupees(it.subtotal_lkr)}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="flex justify-between border-t pt-3 text-[13px] font-semibold">
        <span>Total</span>
        <span className="font-mono tabular-nums">{formatRupees(order.total_lkr)}</span>
      </div>

      {order.status !== "dispatched" && (
        <Button className="rounded-[8px]" onClick={onMarkPacked}>
          Mark packed
        </Button>
      )}
    </div>
  );
}
