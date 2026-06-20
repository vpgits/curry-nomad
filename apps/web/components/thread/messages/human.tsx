"use client";

import { useState } from "react";
import { Check, Pencil, X } from "lucide-react";
import type { Message } from "@langchain/langgraph-sdk";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { getContentString } from "@/lib/utils";
import { useStreamContext } from "@/providers/Stream";
import { BranchSwitcher } from "./shared";

export function HumanMessage({ message, isLoading }: { message: Message; isLoading: boolean }) {
  const stream = useStreamContext();
  const meta = stream.getMessagesMetadata(message);
  const parentCheckpoint = meta?.firstSeenState?.parent_checkpoint;
  const content = getContentString(message.content);

  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(content);

  const submitEdit = () => {
    const text = value.trim();
    if (!text) return;
    // Re-submit from the checkpoint before this turn → forks a new branch (the "edit" UX).
    stream.submit(
      { messages: [{ type: "human", content: text, id: message.id }] },
      {
        checkpoint: parentCheckpoint,
        streamMode: ["values"],
        optimisticValues: (prev) => {
          const prevMessages = prev.messages ?? [];
          const idx = prevMessages.findIndex((m) => m.id === message.id);
          const kept = idx === -1 ? prevMessages : prevMessages.slice(0, idx);
          return {
            ...prev,
            messages: [...kept, { type: "human", content: text, id: message.id } as Message],
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
      <div className="max-w-[80%] rounded-2xl bg-primary px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap text-primary-foreground">
        {content}
      </div>
      <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
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
          className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
        >
          <Pencil className="size-3.5" />
        </button>
      </div>
    </div>
  );
}
