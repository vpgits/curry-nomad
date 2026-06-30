"use client";

import { useState } from "react";
import { Check, Pencil, X } from "lucide-react";
import type { Message } from "@langchain/langgraph-sdk";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { getContentString } from "@/lib/utils";
import { buildSubmitConfig } from "@/lib/run-config";
import { useStreamContext } from "@/providers/Stream";
import { BranchSwitcher } from "./shared";

export function HumanMessage({ message, isLoading }: { message: Message; isLoading: boolean }) {
  const stream = useStreamContext();
  const meta = stream.getMessagesMetadata(message);
  const parentCheckpoint = meta?.firstSeenState?.parent_checkpoint;
  const content = getContentString(message.content);

  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(content);

  const submitEdit = async () => {
    const text = value.trim();
    if (!text) return;
    // Without the fork checkpoint, stream.submit would run from HEAD and silently APPEND the edit at
    // the end of the thread instead of forking in place. Bail loudly rather than corrupt the thread.
    // (If this fires, the turn's checkpoint isn't in the fetched history — see fetchStateHistory in
    // providers/Stream.tsx.)
    if (!parentCheckpoint) {
      toast.error("Can't edit this turn — its checkpoint hasn't loaded yet. Try again in a moment.");
      return;
    }
    // Give the edited turn a FRESH id — do NOT reuse message.id. The edit forks a sibling off the
    // same parent_checkpoint, so reusing the id means BOTH the original and the edited human message
    // carry it. getMessagesMetadata resolves a message's branch via `findLast(history, …includes(id))`,
    // which matches the OLDEST occurrence — i.e. the original (now-inactive) branch's checkpoint. That
    // checkpoint isn't on the active branch path, so `branchByCheckpoint` misses, branchOptions comes
    // back undefined, and the version switcher never renders on the edited bubble. A unique id is only
    // present in the edited branch, so firstSeenState lands on the active branch and the switcher shows.
    const newId = crypto.randomUUID();
    // Carry the per-run config (Google token + Author-UI mode) so editing a workspace turn doesn't
    // run tokenless and degrade to the "connect" stub — see lib/run-config.ts.
    const runConfig = await buildSubmitConfig();
    // Re-submit from the checkpoint before this turn → forks a new branch (the "edit" UX).
    stream.submit(
      { messages: [{ type: "human", content: text, id: newId }] },
      {
        checkpoint: parentCheckpoint,
        streamMode: ["values"],
        ...runConfig,
        optimisticValues: (prev) => {
          const prevMessages = prev.messages ?? [];
          // Locate the truncation point by the ORIGINAL id (that's what's in `prev`), then drop it and
          // everything after, and append the edited turn under its new id.
          const idx = prevMessages.findIndex((m) => m.id === message.id);
          const kept = idx === -1 ? prevMessages : prevMessages.slice(0, idx);
          return {
            ...prev,
            messages: [...kept, { type: "human", content: text, id: newId } as Message],
          };
        },
      },
    );
    setEditing(false);
  };

  if (editing) {
    return (
      <div className="flex flex-col items-end gap-2">
        <Textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          rows={3}
          autoFocus
          className="max-w-[80%] resize-y"
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              submitEdit();
            }
            if (e.key === "Escape") {
              setValue(content);
              setEditing(false);
            }
          }}
        />
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => { setValue(content); setEditing(false); }}>
            <X /> Cancel
          </Button>
          <Button size="sm" disabled={isLoading || !value.trim()} onClick={submitEdit}>
            <Check /> Save
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="group flex flex-col items-end gap-1">
      <div className="max-w-[75%] rounded-[13px_5px_13px_13px] bg-ink px-[15px] py-[11px] text-[13.5px] leading-[1.5] whitespace-pre-wrap text-ink-foreground sm:max-w-[60%]">
        {content}
      </div>
      <div className="flex items-center gap-1">
        {/* Branch nav stays VISIBLE whenever alternate versions of this turn exist (editing forks a
            branch), so the alternates are discoverable — not hidden behind hover. */}
        <BranchSwitcher
          branch={meta?.branch}
          branchOptions={meta?.branchOptions}
          onSelect={(b) => stream.setBranch(b)}
          disabled={isLoading}
        />
        <button
          type="button"
          title="Edit"
          aria-label="Edit message"
          disabled={isLoading}
          onClick={() => { setValue(content); setEditing(true); }}
          className="rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-muted hover:text-foreground disabled:opacity-40 group-hover:opacity-100"
        >
          <Pencil className="size-3.5" />
        </button>
      </div>
    </div>
  );
}
