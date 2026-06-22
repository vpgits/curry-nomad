import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export type PillTone = "neutral" | "brand" | "success" | "warning" | "danger" | "info" | "ink";

// Status pills — the design's tint-bg + edge-border + coloured-text chip. Always paired with a
// label (status is never colour alone). Callers add a leading "●" dot where the design shows one.
const TONES: Record<PillTone, string> = {
  neutral: "border-border bg-secondary text-secondary-foreground",
  brand: "border-brand-edge bg-brand-tint text-brand-text",
  success: "border-success-edge bg-success-tint text-success-text",
  warning: "border-warning-edge bg-warning-tint text-warning-text",
  danger: "border-danger-edge bg-danger-tint text-danger-text",
  info: "border-info-edge bg-info-tint text-info-text",
  ink: "border-transparent bg-ink text-ink-foreground",
};

export function StatusPill({
  tone = "neutral",
  className,
  ...props
}: ComponentProps<"span"> & { tone?: PillTone }) {
  return (
    <span
      className={cn(
        "inline-flex w-fit items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold whitespace-nowrap",
        TONES[tone],
        className,
      )}
      {...props}
    />
  );
}
