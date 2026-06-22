"use client";

import { AppShell } from "@/components/app-shell";
import { OrdersSection } from "@/components/operations/OrdersSection";

export default function OrdersPage() {
  return (
    <AppShell title="Orders" subtitle="24 today · 15 pending">
      <OrdersSection />
    </AppShell>
  );
}
