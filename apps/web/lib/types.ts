// Mirrors the Pydantic contracts in apps/nora/src/nora/schemas.py (the marketing VideoBrief),
// the human_review interrupt payload, and the custom additional_kwargs the orchestrator attaches
// to its final messages (see apps/nora/src/nora/orchestrator.py) — so the UI renders them
// type-safely.

import type { Message } from "@langchain/langgraph-sdk";
import type { UIMessage } from "@langchain/langgraph-sdk/react-ui";

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

// One tool call the analytics agent made (describe_table / run_sql), paired with its result —
// the matching ToolMessage content (query rows, schema, or a SQL error it then repairs).
export interface ToolCallTrace {
  name: string;
  args: Record<string, unknown>;
  result: string;
}

// One step of the agent loop: the calls issued together in a single AIMessage ran in parallel;
// steps are ordered (each turn saw the previous results). Mirrors orchestrator.py's tool_trace.
export interface ToolTraceStep {
  calls: ToolCallTrace[];
}

// The custom payload the orchestrator stashes on its final AI message.
export interface NoraAdditionalKwargs {
  tool_trace?: ToolTraceStep[];
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

// The analytics generative-UI dashboard (mirrors AnalyticsDashboard in schemas.py). Rendered by
// the useStream UI via LoadExternalComponent.
export interface DashboardStat {
  label: string;
  value: string;
  hint?: string | null;
}

export interface DashboardTable {
  columns: string[];
  rows: string[][];
}

export interface AnalyticsDashboardData {
  title: string;
  stats: DashboardStat[];
  table?: DashboardTable | null;
}

// Orchestrator graph state surfaced by useStream. Must be a `type` (not an interface) so it
// satisfies useStream's `Record<string, unknown>` state constraint.
export type NoraState = {
  messages: Message[];
  // Generative-UI messages pushed by the backend (push_ui_message); rendered via LoadExternalComponent.
  ui?: UIMessage[];
};

// Update type accepted by stream.submit() — a fresh human turn.
export type NoraUpdate = {
  messages?: Message[] | Message | string;
};
