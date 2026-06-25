// The compact gen-UI marker the `workspace` capability pushes — it both labels the turn as the
// Workspace agent (via the ModeChip in ai.tsx) and shows, at a glance, which Google tools Nora used.
export function WorkspaceActionsCard({ tools }: { tools?: string[] }) {
  const unique = Array.from(new Set((tools ?? []).filter(Boolean)));
  if (unique.length === 0) return null;
  return (
    <div className="rounded-[5px_13px_13px_13px] border border-info-edge bg-info-tint/30 px-[15px] py-2.5 text-[12px] text-muted-foreground">
      <span className="font-semibold text-info-text">Google Workspace</span> ·{" "}
      {unique.join(", ")}
    </div>
  );
}
