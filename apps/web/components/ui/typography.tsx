import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

// Mono — every number, SKU, timestamp, currency reads in IBM Plex Mono so columns align.
export function Mono({ className, ...props }: ComponentProps<"span">) {
  return <span className={cn("font-mono tabular-nums", className)} {...props} />;
}

// Eyebrow — the uppercase mono label that captions cards, KPIs and table headers.
export function Eyebrow({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "font-mono text-[10px] tracking-[0.1em] text-muted-foreground uppercase",
        className,
      )}
      {...props}
    />
  );
}

// KpiValue — the large hero number (sans per the hi-fi, not mono).
export function KpiValue({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      className={cn("text-[25px] leading-none font-semibold tracking-[-0.015em]", className)}
      {...props}
    />
  );
}
