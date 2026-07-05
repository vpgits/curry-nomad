"use client";

import type { ComponentType, ReactNode } from "react";
import Link from "next/link";
import { AlertTriangle, Play } from "lucide-react";

import { KpiCard } from "@/components/ui/kpi-card";
import { Eyebrow } from "@/components/ui/typography";
import { useHomeSummary } from "@/lib/home";
import { formatRupeesShort } from "@/lib/ops-types";
import { cn } from "@/lib/utils";

// Revenue sparkline (KPI) + 7-week bars — plain divs (no chart lib); last bar is the accent.
const SPARK = [6, 9, 7, 12, 10, 16];
const WEEKS = [48, 58, 44, 70, 64, 80, 92];

export function HomeDashboard() {
  const s = useHomeSummary();

  const attention: AttentionItem[] = [];
  if (s.pendingApprovals > 0) {
    attention.push({
      href: "/ask",
      icon: Play,
      tone: "brand",
      title:
        s.pendingApprovals === 1
          ? "Instagram post awaiting your review"
          : `${s.pendingApprovals} Instagram posts awaiting review`,
      sub: "Marketing workflow paused for copy review",
      action: "Review →",
      primary: true,
    });
  }
  attention.push({
    href: "/stock",
    icon: AlertTriangle,
    tone: "danger",
    title: `${s.lowStock} SKUs below reorder point`,
    sub: `≈ ${formatRupeesShort(s.restockEstimate)} to restock`,
    action: "Reorder →",
  });

  return (
    <>
      {/* KPI row */}
      <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard label="Revenue · 30d" value={formatRupeesShort(s.revenue30d)}>
          <div className="mt-2 flex items-center gap-2">
            <span className="text-[11.5px] font-semibold text-success-text">▲ 12%</span>
            <span className="flex h-4 items-end gap-0.5">
              {SPARK.map((h, i) => (
                <span
                  key={i}
                  className={cn(
                    "w-[3px] rounded-[1px]",
                    i === SPARK.length - 1 ? "bg-brand" : "bg-chart-2",
                  )}
                  style={{ height: h }}
                />
              ))}
            </span>
          </div>
        </KpiCard>
        <KpiCard
          label="Orders today"
          value={s.ordersToday}
          sub={`${s.ordersPending} pending · ${s.ordersDispatched} dispatched`}
        />
        <KpiCard
          label="Low stock"
          tone="danger"
          value={`${s.lowStock} SKUs`}
          sub={`≈ ${formatRupeesShort(s.restockEstimate)} to restock`}
        />
        <KpiCard
          label="Deliveries pending"
          value={s.deliveriesPending}
          sub="1 van · ready to route"
        />
      </div>

      {/* two columns */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.5fr_1fr]">
        {/* left — needs your attention */}
        <div className="flex flex-col rounded-[14px] border bg-card p-[18px]">
          <div className="flex items-center gap-2.5">
            <span className="size-[7px] rounded-full bg-brand" />
            <div className="text-sm font-semibold">Needs your attention</div>
            <span className="ml-auto font-mono text-[10px] text-muted-foreground">
              {attention.length} {attention.length === 1 ? "item" : "items"}
            </span>
          </div>
          <div className="mt-0.5 mb-4 text-[11.5px] text-muted-foreground">
            Everything across the business that wants a decision
          </div>
          <div className="flex flex-col gap-2.5">
            {attention.map((a) => (
              <AttentionRow key={a.href} item={a} />
            ))}
          </div>

          <Eyebrow className="mt-[18px] mb-2.5 text-[10px]">Recent from Nora</Eyebrow>
          <div className="flex flex-col gap-2.5">
            <RecentRow>
              Best-seller in Colombo → <b>Jaffna Curry Blend</b>
            </RecentRow>
            <RecentRow>
              Refund rate on blends → <b>2.1%</b>
            </RecentRow>
          </div>
        </div>

        {/* right column */}
        <div className="flex min-w-0 flex-col gap-4">
          <div className="rounded-[14px] border bg-card p-[18px]">
            <div className="mb-3.5 flex items-baseline justify-between">
              <div className="text-sm font-semibold">Revenue</div>
              <div className="font-mono text-[10px] text-muted-foreground">last 7 weeks</div>
            </div>
            <div className="flex h-24 items-end gap-2.5">
              {WEEKS.map((h, i) => (
                <div
                  key={i}
                  className={cn(
                    "flex-1 rounded-t-[4px]",
                    i === WEEKS.length - 1 ? "bg-brand" : "bg-chart-2",
                  )}
                  style={{ height: h }}
                />
              ))}
            </div>
            <div className="mt-2 flex justify-between font-mono text-[9px] text-muted-foreground">
              <span>W1</span>
              <span>W7</span>
            </div>
          </div>

          <div className="flex-1 rounded-[14px] border bg-card p-[18px]">
            <div className="mb-3.5 text-sm font-semibold">Quick actions</div>
            <div className="flex flex-wrap gap-2.5">
              <QuickChip href="/stock">Receive stock</QuickChip>
              <QuickChip href="/orders">New order</QuickChip>
              <QuickChip href="/ask" accent>
                ✦ Make an ad
              </QuickChip>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

type Tone = "brand" | "danger" | "info";
type AttentionItem = {
  href: string;
  icon: ComponentType<{ className?: string }>;
  tone: Tone;
  title: string;
  sub: string;
  action: string;
  primary?: boolean;
};

const ICON_TONE: Record<Tone, string> = {
  brand: "bg-brand-tint border-brand-edge text-brand-text",
  danger: "bg-danger-tint border-danger-edge text-danger-text",
  info: "bg-info-tint border-info-edge text-info-text",
};

function AttentionRow({ item }: { item: AttentionItem }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      className="flex items-center gap-3 rounded-[10px] border p-3 transition-colors hover:bg-accent"
    >
      <span
        className={cn(
          "flex size-[34px] shrink-0 items-center justify-center rounded-[8px] border",
          ICON_TONE[item.tone],
        )}
      >
        <Icon className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px] font-medium">{item.title}</div>
        <div className="truncate text-[11.5px] text-muted-foreground">{item.sub}</div>
      </div>
      <span
        className={cn(
          "shrink-0 rounded-[7px] px-3.5 py-1.5 text-[12px] font-medium",
          item.primary
            ? "bg-ink text-ink-foreground"
            : "border bg-secondary text-foreground",
        )}
      >
        {item.action}
      </span>
    </Link>
  );
}

function RecentRow({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex size-[22px] shrink-0 items-center justify-center rounded-[6px] bg-ink font-mono text-[10px] text-ink-foreground">
        N
      </span>
      <span className="min-w-0 flex-1 truncate text-[12.5px] text-foreground/80">{children}</span>
      <span className="shrink-0 rounded-full bg-ink px-2 py-px text-[9.5px] font-semibold text-ink-foreground">
        Agent
      </span>
    </div>
  );
}

function QuickChip({
  href,
  accent,
  children,
}: {
  href: string;
  accent?: boolean;
  children: ReactNode;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "rounded-[8px] border px-3.5 py-2.5 text-[12.5px] transition-colors",
        accent
          ? "border-brand-edge bg-brand-tint font-semibold text-brand-text"
          : "hover:border-brand-edge",
      )}
    >
      {children}
    </Link>
  );
}
