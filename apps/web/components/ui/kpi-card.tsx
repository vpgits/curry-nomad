import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import { Eyebrow, KpiValue } from "./typography";

type Tone = "default" | "danger" | "success";

// A flat KPI stat card (border only, no shadow). `tone` tints the whole card + colours the value
// for status KPIs (e.g. low stock = danger, route savings = success). The `children` slot hosts a
// sparkline / delta row beneath the value.
export function KpiCard({
  label,
  value,
  sub,
  tone = "default",
  children,
  className,
}: {
  label: ReactNode;
  value: ReactNode;
  sub?: ReactNode;
  tone?: Tone;
  children?: ReactNode;
  className?: string;
}) {
  const toneText =
    tone === "danger" ? "text-danger-text" : tone === "success" ? "text-success-text" : "";

  return (
    <div
      className={cn(
        "rounded-[12px] border bg-card p-4",
        tone === "danger" && "border-danger-edge bg-danger-tint/40",
        tone === "success" && "border-success-edge bg-success-tint/40",
        className,
      )}
    >
      <Eyebrow className={toneText}>{label}</Eyebrow>
      <KpiValue className={cn("mt-[7px]", toneText)}>{value}</KpiValue>
      {sub && (
        <div className={cn("mt-2 text-[11.5px]", toneText || "text-muted-foreground")}>{sub}</div>
      )}
      {children}
    </div>
  );
}
