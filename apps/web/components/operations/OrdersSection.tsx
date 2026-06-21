"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { ops } from "@/lib/ops";
import { formatLkr, LOCAL_CITIES, type Order, type StockRow } from "@/lib/ops-types";

const selectClass =
  "h-8 rounded-2xl border border-border bg-background px-3 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30 outline-none";

type Line = { sku: string; quantity: string };

const statusVariant = (status: string) =>
  status === "dispatched" ? "secondary" : status === "cancelled" ? "destructive" : "default";

export function OrdersSection() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [products, setProducts] = useState<StockRow[]>([]);
  const [loading, setLoading] = useState(true);
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

  // Load once on mount (setState inside the promise callback, not synchronously). `load` is kept
  // for refreshing after a mutation.
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
      toast.success(`Order #${order.order_id} reserved · ${formatLkr(order.total_lkr)}`);
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

  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle className="flex items-center justify-between text-base">
          <span>Orders</span>
          <Button size="xs" onClick={() => setOpen(true)}>
            <Plus /> New order
          </Button>
        </CardTitle>
      </CardHeader>

      <CardContent>
        {loading ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Loading orders…</p>
        ) : orders.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No orders yet. Create one to reserve stock.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full border-collapse text-sm">
              <thead className="bg-muted/50">
                <tr>
                  <th className="border-b px-3 py-2 text-left font-medium">Order</th>
                  <th className="border-b px-3 py-2 text-left font-medium">Customer</th>
                  <th className="border-b px-3 py-2 text-left font-medium">Items</th>
                  <th className="border-b px-3 py-2 text-right font-medium">Total</th>
                  <th className="border-b px-3 py-2 text-left font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((o) => (
                  <tr key={o.order_id} className="hover:bg-muted/30">
                    <td className="border-b px-3 py-2 tabular-nums">#{o.order_id}</td>
                    <td className="border-b px-3 py-2">{o.customer_name}</td>
                    <td className="border-b px-3 py-2 text-muted-foreground">
                      {o.items.map((it) => `${it.quantity}× ${it.sku}`).join(", ")}
                    </td>
                    <td className="border-b px-3 py-2 text-right tabular-nums">
                      {formatLkr(o.total_lkr)}
                    </td>
                    <td className="border-b px-3 py-2">
                      <Badge variant={statusVariant(o.status)}>{o.status}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>

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
                      setLines((ls) => ls.map((l, j) => (j === i ? { ...l, sku: e.target.value } : l)))
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
                    placeholder="12 Galle Rd, Colombo 03"
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
    </Card>
  );
}
