"use client";

// The two-mode lane pinned above the conversation — makes the analytics agent vs marketing workflow
// split explicit (the teaching point of this app).
function ModeCard({ dot, title, desc }: { dot: string; title: string; desc: string }) {
  return (
    <div className="flex-1 rounded-[10px] border bg-card px-3.5 py-[11px]">
      <div className="flex items-center gap-2 text-[12.5px] font-semibold">
        <span className={`size-2 rounded-[2px] ${dot}`} />
        {title}
      </div>
      <div className="mt-0.5 text-[11px] text-muted-foreground">{desc}</div>
    </div>
  );
}

export function AskNoraModeLane() {
  return (
    <div className="flex shrink-0 gap-2.5 border-b bg-background px-[26px] py-3.5">
      <ModeCard
        dot="bg-ink"
        title="Analytics agent"
        desc="Queries the database and shows its work"
      />
      <ModeCard
        dot="bg-brand"
        title="Marketing workflow"
        desc="Drafts ads and pauses for your approval"
      />
    </div>
  );
}
