"use client";

import { AppShell } from "@/components/app-shell";
import { HomeDashboard } from "@/components/home/HomeDashboard";

// Home — the overview dashboard. One glance at business health; routes the operator to whatever
// needs a decision. Composes existing ops data; see components/home/HomeDashboard.tsx.
export default function HomePage() {
  return (
    <AppShell title="Good morning, Operator" subtitle="Tuesday 23 June · Colombo · ☀ 29°">
      <div className="min-h-0 flex-1 overflow-y-auto bg-body-bg">
        <div className="flex flex-col gap-[18px] px-[26px] py-[22px]">
          <HomeDashboard />
        </div>
      </div>
    </AppShell>
  );
}
