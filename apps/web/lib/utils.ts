import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { Message } from "@langchain/langgraph-sdk";

import type { NoraAdditionalKwargs } from "@/lib/types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Message content is either a string or an array of content blocks; flatten to plain text.
export function getContentString(content: Message["content"]): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((block) =>
      typeof block === "string" ? block : ((block as { text?: string })?.text ?? ""),
    )
    .join("");
}

// The orchestrator stashes tool_trace / video_brief on its final message's additional_kwargs.
export function getNoraKwargs(message: Message): NoraAdditionalKwargs {
  return (message as { additional_kwargs?: NoraAdditionalKwargs }).additional_kwargs ?? {};
}

// Pull just the model's reasoning chain out of a message. Anthropic extended thinking (and other
// reasoning models) emit chain-of-thought as content blocks separate from the answer — type
// "thinking" (Anthropic) or "reasoning" (standard content blocks) — so getContentString ignores it
// and the answer text stays clean. Falls back to additional_kwargs.reasoning_content. Returns ""
// when the model emits no reasoning (e.g. the default gpt-4o), so the UI simply renders nothing.
export function getReasoningString(message: Message): string {
  const content = message.content;
  let out = "";
  if (Array.isArray(content)) {
    for (const block of content) {
      if (typeof block === "string") continue;
      const b = block as { type?: string; thinking?: string; reasoning?: string };
      if (b.type === "thinking" && b.thinking) out += b.thinking;
      else if (b.type === "reasoning" && b.reasoning) out += b.reasoning;
    }
  }
  if (out) return out;
  const reasoning = getNoraKwargs(message).reasoning_content;
  return typeof reasoning === "string" ? reasoning : "";
}
