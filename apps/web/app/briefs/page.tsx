"use client";

import { AppShell } from "@/components/app-shell";
import { BriefsApproval } from "@/components/briefs/BriefsApproval";

// Marketing briefs — the relocated HITL approval gate. Reads the paused marketing run from the
// shared (hoisted) stream and resumes it with the operator's decision. Reachable from Home, from
// the chat "Open review →" button, and from the sidebar.
export default function BriefsPage() {
  return (
    <AppShell title="Marketing briefs" subtitle="Review the proposed ad before the workflow spends compute">
      <BriefsApproval />
    </AppShell>
  );
}
