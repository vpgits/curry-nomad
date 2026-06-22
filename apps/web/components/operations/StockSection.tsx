"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { KpiCard } from "@/components/ui/kpi-card";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { StatusPill } from "@/components/ui/status-pill";
import { Textarea } from "@/components/ui/textarea";
import { ops } from "@/lib/ops";
import { formatRupees, formatRupeesShort, type StockRow } from "@/lib/ops-types";
import { cn } from "@/lib/utils";

type SheetState = { open: boolean; mode: "receive" | "adjust"; product: StockRow | null };

const CLOSED: SheetState = { open: false, mode: "receive", product: null };
const ROW = "grid grid-cols-[2.2fr_1fr_1fr_1fr_1.3fr] items-center";

export function StockSection() {
  const [rows, setRows] = useState<StockRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
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

  useEffect(() => {
    ops
      .getStock()
      .then(setRows)
      .catch((e) => toast.error((e as Error).message))
      .finally(() => setLoading(false));
  }, []);

  const openSheet = (mode: SheetState["mode"], product: StockRow | null) => {
    setQty("");
    setReason("");
    setSheet({ open: true, mode, product: product ?? rows[0] ?? null });
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
        await ops.receiveStock({
          product_id: sheet.product.product_id,
          qty: n,
          reason: reason || undefined,
        });
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
  const q = query.trim().toLowerCase();
  const filtered = q
    ? rows.filter((r) => r.name.toLowerCase().includes(q) || r.sku.toLowerCase().includes(q))
    : rows;
  // On-hand value isn't in the ops contract (StockRow has no unit cost), so it's a prototype figure.
  const onHandValue = 842_000;
  const restockEstimate = 96_000;

  return (
    <>
      {/* action row */}
      <div className="flex items-center gap-3">
        {lowCount > 0 && (
          <StatusPill tone="danger">{lowCount} below reorder point</StatusPill>
        )}
        <div className="ml-auto flex items-center gap-2.5">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search…"
            className="h-9 w-44 rounded-[8px] bg-card text-[12.5px]"
          />
          <Button
            className="h-9 rounded-[8px] text-[12.5px]"
            onClick={() => openSheet("receive", null)}
          >
            + Receive stock
          </Button>
        </div>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-3">
        <KpiCard label="On-hand value" value={formatRupees(onHandValue)} />
        <KpiCard label="Active SKUs" value={rows.length || "—"} />
        <KpiCard
          label="Reorder now"
          value={`${lowCount} SKUs`}
          tone="danger"
          sub={`≈ ${formatRupeesShort(restockEstimate)} to restock`}
        />
      </div>

      {/* table */}
      <div className="overflow-hidden rounded-[14px] border bg-card">
        <div className={cn(ROW, "border-b bg-panel")}>
          <HeadCell>Product</HeadCell>
          <HeadCell className="text-right">On hand</HeadCell>
          <HeadCell className="text-right">Reserved</HeadCell>
          <HeadCell className="text-right">Available</HeadCell>
          <HeadCell className="text-right">Actions</HeadCell>
        </div>
        {loading ? (
          <p className="py-8 text-center text-sm text-muted-foreground">Loading stock…</p>
        ) : filtered.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">No matching products.</p>
        ) : (
          <div className="divide-y divide-border-soft">
            {filtered.map((r) => (
              <div key={r.product_id} className={cn(ROW, r.low_stock && "bg-danger-tint/30")}>
                <div className="px-4 py-[13px]">
                  <div className="flex items-center gap-2 text-[13px]">
                    {r.name}
                    {r.low_stock && (
                      <StatusPill tone="danger" className="px-1.5 py-0 text-[9.5px]">
                        low
                      </StatusPill>
                    )}
                  </div>
                  <div className="font-mono text-[10px] text-muted-foreground">{r.sku}</div>
                </div>
                <NumCell>{r.on_hand}</NumCell>
                <NumCell>{r.reserved}</NumCell>
                <NumCell className={cn(r.low_stock && "font-medium text-danger-text")}>
                  {r.available}
                </NumCell>
                <div className="flex justify-end gap-1 px-3 py-[13px]">
                  <Button size="xs" variant="ghost" onClick={() => openSheet("receive", r)}>
                    Receive
                  </Button>
                  <Button size="xs" variant="ghost" onClick={() => openSheet("adjust", r)}>
                    Adjust
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

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
              <span className="font-medium">Product</span>
              <select
                className="h-9 rounded-[8px] border border-input bg-background px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30"
                value={sheet.product?.product_id ?? ""}
                onChange={(e) =>
                  setSheet((s) => ({
                    ...s,
                    product: rows.find((r) => r.product_id === Number(e.target.value)) ?? null,
                  }))
                }
              >
                {rows.map((r) => (
                  <option key={r.product_id} value={r.product_id}>
                    {r.name} ({r.sku})
                  </option>
                ))}
              </select>
            </label>
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
                Reason{" "}
                {sheet.mode === "adjust" && (
                  <span className="text-muted-foreground">(required for write-offs)</span>
                )}
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
    </>
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

function NumCell({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("px-4 py-[13px] text-right font-mono text-[13px] tabular-nums", className)}>
      {children}
    </div>
  );
}
