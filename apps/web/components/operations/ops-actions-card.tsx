// The compact gen-UI marker the `operations` capability pushes — it both labels the turn as the
// Operations agent (via the ModeChip in ai.tsx) and shows, at a glance, which order/stock/customer
// actions Nora performed. Mirrors WorkspaceActionsCard.
export function OpsActionsCard({ tools }: { tools?: string[] }) {
  const unique = Array.from(new Set((tools ?? []).filter(Boolean))).map((t) => t.replace(/_/g, " "));
  if (unique.length === 0) return null;
  return (
    <div className="rounded-[5px_13px_13px_13px] border border-success-edge bg-success-tint/30 px-[15px] py-2.5 text-[12px] text-muted-foreground">
      <span className="font-semibold text-success-text">Operations</span> · {unique.join(", ")}
    </div>
  );
}
