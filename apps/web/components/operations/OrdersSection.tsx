"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { StatusPill } from "@/components/ui/status-pill";
import { useIsMobile } from "@/hooks/use-mobile";
import { ops } from "@/lib/ops";
import { formatRupees, LOCAL_CITIES, type Order, type StockRow } from "@/lib/ops-types";
import { cn } from "@/lib/utils";
import { OrderDrawer } from "./OrderDrawer";
import { orderStatusLabel, orderStatusTone } from "./order-status";

const selectClass =
  "h-9 rounded-[8px] border border-input bg-background px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30";

type Line = { sku: string; quantity: string };
type Filter = "all" | "pending" | "dispatched";

// "Packed" is omitted — the backend only has reserved → dispatched, so a Packed filter would never
// match. Filtering "pending" maps to the backend's "reserved" state.
const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "pending", label: "Pending" },
  { key: "dispatched", label: "Dispatched" },
];

const ROW = "grid grid-cols-[0.8fr_1.5fr_1fr_1fr] items-center";

export function OrdersSection() {
  const isMobile = useIsMobile();
  const [orders, setOrders] = useState<Order[]>([]);
  const [products, setProducts] = useState<StockRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>("all");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const [customerId, setCustomerId] = useState("1");
  const [lines, setLines] = useState<Line[]>([{ sku: "", quantity: "1" }]);
  const [withDelivery, setWithDelivery] = useState(false);
  const [city, setCity] = useState<string>(LOCAL_CITIES[0]);
  const [address, setAddress] = useState("");

  const load = useCallback(async () => {
    try {
      const [o, p] = await Promise.all([ops.listOrders(), ops.getStock()]);
      setOrders(o);
      setProducts(p);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    Promise.all([ops.listOrders(), ops.getStock()])
      .then(([o, p]) => {
        setOrders(o);
        setProducts(p);
      })
      .catch((e) => toast.error((e as Error).message))
      .finally(() => setLoading(false));
  }, []);

  const resetForm = () => {
    setCustomerId("1");
    setLines([{ sku: "", quantity: "1" }]);
    setWithDelivery(false);
    setCity(LOCAL_CITIES[0]);
    setAddress("");
  };

  const submit = async () => {
    const parsedLines = lines
      .filter((l) => l.sku)
      .map((l) => ({ sku: l.sku, quantity: Number(l.quantity) }));
    if (parsedLines.length === 0) {
      toast.error("Add at least one product line.");
      return;
    }
    if (parsedLines.some((l) => !Number.isFinite(l.quantity) || l.quantity <= 0)) {
      toast.error("Every line needs a positive quantity.");
      return;
    }
    setBusy(true);
    try {
      const order = await ops.createOrder({
        customer_id: Number(customerId),
        lines: parsedLines,
        delivery: withDelivery && address ? { address, city } : undefined,
      });
      toast.success(`Order #${order.order_id} reserved · ${formatRupees(order.total_lkr)}`);
      setOpen(false);
      resetForm();
      await load();
    } catch (e) {
      // e.g. "Cannot reserve 200 of CIN-ALBA-100: only 40 available." — the oversell limit.
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const visible = orders.filter((o) =>
    filter === "all" ? true : filter === "pending" ? o.status === "reserved" : o.status === filter,
  );
  const selected = orders.find((o) => o.order_id === selectedId) ?? null;

  // "Mark packed" has no backend op (orders go reserved → dispatched), so it's a demo stub.
  const markPacked = () => {
    if (selected) toast.success(`Order #${selected.order_id} marked packed (demo)`);
  };

  return (
    <div className="flex min-h-0 flex-1">
      {/* list */}
      <div className="flex min-w-0 flex-1 flex-col border-r">
        <div className="flex shrink-0 items-center gap-2.5 px-[26px] pt-[18px] pb-3">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={cn(
                "rounded-full px-3.5 py-1.5 text-[12.5px] font-medium transition-colors",
                filter === f.key
                  ? "bg-ink text-ink-foreground"
                  : "border bg-card text-foreground hover:border-brand-edge",
              )}
            >
              {f.label}
            </button>
          ))}
          <Button className="ml-auto h-9 rounded-[8px] text-[12.5px]" onClick={() => setOpen(true)}>
            <Plus /> New order
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-[26px] pb-[22px]">
          <div className="overflow-hidden rounded-[14px] border bg-card">
            <div className={cn(ROW, "border-b bg-panel")}>
              <HeadCell>Order</HeadCell>
              <HeadCell>Customer</HeadCell>
              <HeadCell>Status</HeadCell>
              <HeadCell className="text-right">Total</HeadCell>
            </div>
            {loading ? (
              <p className="py-8 text-center text-sm text-muted-foreground">Loading orders…</p>
            ) : visible.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">No orders here yet.</p>
            ) : (
              <div className="divide-y divide-border-soft">
                {visible.map((o) => (
                  <button
                    key={o.order_id}
                    onClick={() => setSelectedId(o.order_id)}
                    className={cn(
                      ROW,
                      "w-full text-left transition-colors hover:bg-accent",
                      o.order_id === selectedId && "bg-accent",
                    )}
                  >
                    <div className="px-4 py-[13px] font-mono text-[12.5px] tabular-nums">
                      #{o.order_id}
                    </div>
                    <div className="px-4 py-[13px] text-[13px]">{o.customer_name}</div>
                    <div className="px-4 py-[13px]">
                      <StatusPill tone={orderStatusTone(o.status)} className="text-[10px]">
                        {orderStatusLabel(o.status)}
                      </StatusPill>
                    </div>
                    <div className="px-4 py-[13px] text-right font-mono text-[12.5px] tabular-nums">
                      {formatRupees(o.total_lkr)}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* detail drawer — inline on desktop */}
      {selected && !isMobile && (
        <div className="w-[316px] shrink-0 overflow-y-auto bg-background">
          <OrderDrawer order={selected} onMarkPacked={markPacked} />
        </div>
      )}

      {/* detail drawer — Sheet on mobile */}
      <Sheet
        open={isMobile && !!selected}
        onOpenChange={(o) => {
          if (!o) setSelectedId(null);
        }}
      >
        <SheetContent className="w-[330px] p-0 sm:max-w-none">
          <SheetHeader className="sr-only">
            <SheetTitle>Order detail</SheetTitle>
            <SheetDescription>Selected order line items and actions.</SheetDescription>
          </SheetHeader>
          {selected && <OrderDrawer order={selected} onMarkPacked={markPacked} />}
        </SheetContent>
      </Sheet>

      {/* new order Sheet */}
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent className="overflow-y-auto">
          <SheetHeader>
            <SheetTitle>New order</SheetTitle>
            <SheetDescription>
              Reserving stock is transactional: unknown SKUs and overselling are rejected, totals are
              computed exactly.
            </SheetDescription>
          </SheetHeader>

          <div className="flex flex-col gap-4 px-6">
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium">Customer ID</span>
              <Input
                type="number"
                value={customerId}
                onChange={(e) => setCustomerId(e.target.value)}
              />
            </label>

            <div className="flex flex-col gap-2">
              <span className="text-sm font-medium">Line items</span>
              {lines.map((line, i) => (
                <div key={i} className="flex items-center gap-2">
                  <select
                    className={`${selectClass} flex-1`}
                    value={line.sku}
                    onChange={(e) =>
                      setLines((ls) =>
                        ls.map((l, j) => (j === i ? { ...l, sku: e.target.value } : l)),
                      )
                    }
                  >
                    <option value="">Select product…</option>
                    {products.map((p) => (
                      <option key={p.product_id} value={p.sku}>
                        {p.name} ({p.available} avail.)
                      </option>
                    ))}
                  </select>
                  <Input
                    type="number"
                    className="w-20"
                    value={line.quantity}
                    onChange={(e) =>
                      setLines((ls) =>
                        ls.map((l, j) => (j === i ? { ...l, quantity: e.target.value } : l)),
                      )
                    }
                  />
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}
                    disabled={lines.length === 1}
                  >
                    <Trash2 />
                  </Button>
                </div>
              ))}
              <Button
                size="xs"
                variant="outline"
                className="w-fit"
                onClick={() => setLines((ls) => [...ls, { sku: "", quantity: "1" }])}
              >
                <Plus /> Add line
              </Button>
            </div>

            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={withDelivery}
                onChange={(e) => setWithDelivery(e.target.checked)}
              />
              <span className="font-medium">Attach a delivery</span>
            </label>

            {withDelivery && (
              <div className="flex flex-col gap-3 rounded-lg border bg-muted/20 p-3">
                <label className="flex flex-col gap-1.5 text-sm">
                  <span className="font-medium">City</span>
                  <select
                    className={selectClass}
                    value={city}
                    onChange={(e) => setCity(e.target.value)}
                  >
                    {LOCAL_CITIES.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1.5 text-sm">
                  <span className="font-medium">Address</span>
                  <Input
                    value={address}
                    onChange={(e) => setAddress(e.target.value)}
                    placeholder="No. 215, Galle Road, Kollupitiya, Colombo 00300"
                  />
                </label>
              </div>
            )}
          </div>

          <SheetFooter>
            <Button onClick={submit} disabled={busy}>
              {busy ? "Reserving…" : "Create order"}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </div>
  );
}

function HeadCell({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "px-4 py-[11px] font-mono text-[9.5px] tracking-[0.06em] text-muted-foreground uppercase",
        className,
      )}
    >
      {children}
    </div>
  );
}
