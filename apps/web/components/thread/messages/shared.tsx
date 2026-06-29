"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

// Navigate between alternate branches produced by editing a message or regenerating a response.
// `branch`/`branchOptions` come from stream.getMessagesMetadata(message).
export function BranchSwitcher({
  branch,
  branchOptions,
  onSelect,
  disabled,
}: {
  branch: string | undefined;
  branchOptions: string[] | undefined;
  onSelect: (branch: string) => void;
  disabled?: boolean;
}) {
  if (!branchOptions || !branch || branchOptions.length <= 1) return null;
  const index = branchOptions.indexOf(branch);

  return (
    <div className="flex items-center gap-1 text-xs text-muted-foreground">
      <button
        type="button"
        className="rounded p-0.5 hover:bg-muted disabled:opacity-40"
        disabled={disabled || index <= 0}
        onClick={() => onSelect(branchOptions[index - 1])}
        aria-label="Previous version"
      >
        <ChevronLeft className="size-3.5" />
      </button>
      <span className="tabular-nums">
        {index + 1} / {branchOptions.length}
      </span>
      <button
        type="button"
        className="rounded p-0.5 hover:bg-muted disabled:opacity-40"
        disabled={disabled || index >= branchOptions.length - 1}
        onClick={() => onSelect(branchOptions[index + 1])}
        aria-label="Next version"
      >
        <ChevronRight className="size-3.5" />
      </button>
    </div>
  );
}
