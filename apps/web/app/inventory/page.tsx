"use client";

import { useState } from "react";

import { AppShell } from "@/components/app-shell";
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

// The deterministic operations console. No agent, no LLM — it talks straight to the operations
// REST API. This is Phase 1: the real system the agent will later be a mere caller of. It shares
// the AppShell (collapsible sidebar + header bar) with the chat surface, so cross-page nav lives in
// the sidebar and the Stock/Orders/Routes tabs are just this page's own body sub-nav.
export default function InventoryPage() {
  const [section, setSection] = useState<SectionKey>("stock");

  return (
    <AppShell
      title="Inventory & Operations"
      subtitle="Curry Nomad · deterministic, non-agentic"
    >
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-8">
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

          {section === "stock" && <StockSection />}
          {section === "orders" && <OrdersSection />}
          {section === "routes" && <RoutesSection />}
        </div>
      </div>
    </AppShell>
  );
}
