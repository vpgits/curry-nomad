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
