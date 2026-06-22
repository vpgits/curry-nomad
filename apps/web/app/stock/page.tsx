"use client";

import { AppShell } from "@/components/app-shell";
import { StockSection } from "@/components/operations/StockSection";

export default function StockPage() {
  return (
    <AppShell title="Stock" subtitle="48 active SKUs · 3 below reorder point">
      <div className="min-h-0 flex-1 overflow-y-auto bg-body-bg">
        <div className="flex flex-col gap-[18px] px-[26px] py-[22px]">
          <StockSection />
        </div>
      </div>
    </AppShell>
  );
}
