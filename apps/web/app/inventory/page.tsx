"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, Boxes } from "lucide-react";

import { OrdersSection } from "@/components/operations/OrdersSection";
import { RoutesSection } from "@/components/operations/RoutesSection";
import { StockSection } from "@/components/operations/StockSection";
import { Button } from "@/components/ui/button";

const SECTIONS = [
  { key: "stock", label: "Stock" },
  { key: "orders", label: "Orders" },
  { key: "routes", label: "Routes" },
] as const;

type SectionKey = (typeof SECTIONS)[number]["key"];

// The deterministic operations console. No agent, no Aegra — it talks straight to the operations
// REST API. This is Phase 1: the real system the agent will later be a mere caller of.
export default function InventoryPage() {
  const [section, setSection] = useState<SectionKey>("stock");

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-5xl flex-col gap-6 px-4 py-8">
      <header className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Boxes className="size-4" />
            </div>
            <div>
              <h1 className="text-base font-semibold leading-tight">Inventory &amp; Operations</h1>
              <p className="text-xs text-muted-foreground">Curry Nomad · deterministic, non-agentic</p>
            </div>
          </div>
          <Button asChild variant="ghost" size="sm">
            <Link href="/">
              <ArrowLeft /> Back to Nora
            </Link>
          </Button>
        </div>

        <div className="flex w-fit gap-1 rounded-2xl border bg-muted/30 p-1">
          {SECTIONS.map((s) => (
            <Button
              key={s.key}
              size="sm"
              variant={section === s.key ? "secondary" : "ghost"}
              onClick={() => setSection(s.key)}
            >
              {s.label}
            </Button>
          ))}
        </div>
      </header>

      {section === "stock" && <StockSection />}
      {section === "orders" && <OrdersSection />}
      {section === "routes" && <RoutesSection />}
    </div>
  );
}
