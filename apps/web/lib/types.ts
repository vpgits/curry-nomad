// Mirrors the Pydantic contracts in apps/nora/src/nora/schemas.py (the marketing VideoBrief),
// the human_review interrupt payload, and the custom additional_kwargs the orchestrator attaches
// to its final messages (see apps/nora/src/nora/orchestrator.py) — so the UI renders them
// type-safely.

import type { Message } from "@langchain/langgraph-sdk";

export interface ScriptBeat {
  t_start_s: number;
  t_end_s: number;
  voiceover: string;
  on_screen_text?: string | null;
}

export interface Shot {
  index: number;
  scene_description: string;
  duration_s: number;
}

export interface ShotPrompt {
  index: number;
  t2v_prompt: string;
}

export interface VideoBrief {
  product_name: string;
  concept: string;
  hook: string;
  target_duration_s: number;
  platform: string;
  script_beats: ScriptBeat[];
  shots: Shot[];
  shot_prompts: ShotPrompt[];
  cta: string;
  music_mood: string;
  hashtags: string[];
  product_facts_used: string[];
}

// One entry of the analytics agent's work — the run_sql / describe_table calls it made.
// The orchestrator's `analytics` node folds these onto the final message's additional_kwargs
// (the intermediate tool-calling messages never reach orchestrator state).
export interface ToolTraceEntry {
  name: string;
  args: Record<string, unknown>;
}

// The custom payload the orchestrator stashes on its final AI message.
export interface NoraAdditionalKwargs {
  tool_trace?: ToolTraceEntry[];
  video_brief?: VideoBrief;
}

// Payload emitted by the marketing human_review node's interrupt().
export interface ReviewInterrupt {
  question: string;
  script_beats: ScriptBeat[];
}

// What we send back on resume (read by human_review in nodes.py).
export interface ReviewDecision {
  approved: boolean;
  edited_script?: ScriptBeat[];
}

// Orchestrator graph state surfaced by useStream. Must be a `type` (not an interface) so it
// satisfies useStream's `Record<string, unknown>` state constraint.
export type NoraState = {
  messages: Message[];
};

// Update type accepted by stream.submit() — a fresh human turn.
export type NoraUpdate = {
  messages?: Message[] | Message | string;
};
