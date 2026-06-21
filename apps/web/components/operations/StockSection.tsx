"use client";

import { useCallback, useEffect, useState } from "react";
import { PackagePlus, SlidersHorizontal } from "lucide-react";
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
import { Textarea } from "@/components/ui/textarea";
import { ops } from "@/lib/ops";
import type { StockRow } from "@/lib/ops-types";

type SheetState = { open: boolean; mode: "receive" | "adjust"; product: StockRow | null };

const CLOSED: SheetState = { open: false, mode: "receive", product: null };

export function StockSection() {
  const [rows, setRows] = useState<StockRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [sheet, setSheet] = useState<SheetState>(CLOSED);
  const [qty, setQty] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setRows(await ops.getStock());
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  // Load once on mount via a promise chain (setState in a callback, not synchronously in the
  // effect body) — the pattern the rest of the app uses. `load` itself is for handler-driven refreshes.
  useEffect(() => {
    ops
      .getStock()
      .then(setRows)
      .catch((e) => toast.error((e as Error).message))
      .finally(() => setLoading(false));
  }, []);

  const openSheet = (mode: SheetState["mode"], product: StockRow) => {
    setQty("");
    setReason("");
    setSheet({ open: true, mode, product });
  };

  const submit = async () => {
    if (!sheet.product) return;
    const n = Number(qty);
    if (!Number.isFinite(n) || n === 0) {
      toast.error("Enter a non-zero quantity.");
      return;
    }
    setBusy(true);
    try {
      if (sheet.mode === "receive") {
        await ops.receiveStock({ product_id: sheet.product.product_id, qty: n, reason: reason || undefined });
        toast.success(`Received ${n} × ${sheet.product.sku}`);
      } else {
        await ops.adjustStock({
          product_id: sheet.product.product_id,
          qty_delta: n,
          reason,
          kind: n < 0 ? "write_off" : "adjust",
        });
        toast.success(`Adjusted ${sheet.product.sku} by ${n}`);
      }
      setSheet(CLOSED);
      await load();
    } catch (e) {
      // The API's business-rule message (e.g. a rejected write-off) surfaces verbatim.
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const lowCount = rows.filter((r) => r.low_stock).length;

  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle className="flex items-center justify-between text-base">
          <span>Stock</span>
          {lowCount > 0 && (
            <Badge variant="destructive">{lowCount} below reorder point</Badge>
          )}
        </CardTitle>
      </CardHeader>

      <CardContent>
        {loading ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Loading stock…</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full border-collapse text-sm">
              <thead className="bg-muted/50">
                <tr>
                  <th className="border-b px-3 py-2 text-left font-medium">Product</th>
                  <th className="border-b px-3 py-2 text-right font-medium">On hand</th>
                  <th className="border-b px-3 py-2 text-right font-medium">Reserved</th>
                  <th className="border-b px-3 py-2 text-right font-medium">Available</th>
                  <th className="border-b px-3 py-2 text-right font-medium">Reorder pt</th>
                  <th className="border-b px-3 py-2 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.product_id} className="hover:bg-muted/30">
                    <td className="border-b px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span>{r.name}</span>
                        {r.low_stock && <Badge variant="destructive">low</Badge>}
                      </div>
                      <div className="text-xs text-muted-foreground">{r.sku}</div>
                    </td>
                    <td className="border-b px-3 py-2 text-right tabular-nums">{r.on_hand}</td>
                    <td className="border-b px-3 py-2 text-right tabular-nums">{r.reserved}</td>
                    <td className="border-b px-3 py-2 text-right tabular-nums">{r.available}</td>
                    <td className="border-b px-3 py-2 text-right tabular-nums text-muted-foreground">
                      {r.reorder_point}
                    </td>
                    <td className="border-b px-3 py-2">
                      <div className="flex justify-end gap-1.5">
                        <Button size="xs" variant="outline" onClick={() => openSheet("receive", r)}>
                          <PackagePlus /> Receive
                        </Button>
                        <Button size="xs" variant="ghost" onClick={() => openSheet("adjust", r)}>
                          <SlidersHorizontal /> Adjust
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>

      <Sheet open={sheet.open} onOpenChange={(o) => setSheet((s) => ({ ...s, open: o }))}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>
              {sheet.mode === "receive" ? "Receive stock" : "Adjust stock"}
              {sheet.product ? ` — ${sheet.product.sku}` : ""}
            </SheetTitle>
            <SheetDescription>
              {sheet.mode === "receive"
                ? "Record an inbound shipment. On-hand goes up; a ledger entry is written."
                : "Correct or write off stock. A negative quantity needs a reason and can't drop on-hand below what's reserved."}
            </SheetDescription>
          </SheetHeader>

          <div className="flex flex-col gap-4 px-6">
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium">
                {sheet.mode === "receive" ? "Quantity received" : "Quantity change (±)"}
              </span>
              <Input
                type="number"
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                placeholder={sheet.mode === "receive" ? "e.g. 500" : "e.g. -20"}
              />
            </label>
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium">
                Reason {sheet.mode === "adjust" && <span className="text-muted-foreground">(required for write-offs)</span>}
              </span>
              <Textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder={sheet.mode === "receive" ? "PO #, supplier…" : "water damage, recount…"}
                rows={2}
              />
            </label>
          </div>

          <SheetFooter>
            <Button onClick={submit} disabled={busy}>
              {busy ? "Saving…" : sheet.mode === "receive" ? "Receive" : "Apply adjustment"}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </Card>
  );
}
