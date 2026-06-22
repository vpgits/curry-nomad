"use client";

import { AppShell } from "@/components/app-shell";
import { RoutesSection } from "@/components/operations/RoutesSection";

export default function RoutesPage() {
  return (
    <AppShell title="Delivery routing" subtitle="9 stops pending · 1 van">
      <div className="min-h-0 flex-1 overflow-y-auto bg-body-bg">
        <div className="flex flex-col gap-[18px] px-[26px] py-[22px]">
          <RoutesSection />
        </div>
      </div>
    </AppShell>
  );
}
