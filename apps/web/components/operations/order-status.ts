import type { PillTone } from "@/components/ui/status-pill";

// Backend order statuses are "reserved" (a new order, stock held) → "dispatched". The redesign
// speaks in "Pending"/"Dispatched"; map the vocabulary here so list + drawer stay consistent.
export function orderStatusLabel(status: string): string {
  if (status === "reserved") return "Pending";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

export function orderStatusTone(status: string): PillTone {
  switch (status) {
    case "dispatched":
      return "info";
    case "cancelled":
      return "danger";
    case "packed":
      return "neutral";
    default:
      return "brand"; // reserved / pending
  }
}
