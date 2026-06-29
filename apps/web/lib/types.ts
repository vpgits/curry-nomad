// Mirrors the Pydantic contracts in apps/nora/src/nora/schemas.py (the marketing VideoBrief),
// the human_review interrupt payload, and the custom additional_kwargs the orchestrator attaches
// to its final messages (see apps/nora/src/nora/orchestrator.py) — so the UI renders them
// type-safely.

import type { Message } from "@langchain/langgraph-sdk";
import type { UIMessage } from "@langchain/langgraph-sdk/react-ui";

export interface ConceptIdea {
  angle: string;
  hook: string;
  rationale: string;
}

export interface ScriptBeat {
  t_start_s: number;
  t_end_s: number;
  voiceover: string;
  on_screen_text?: string | null;
}

export interface Critique {
  passed: boolean;
  issues: string[];
  suggestions: string[];
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

// The custom payload the orchestrator stashes on its final AI message. (The marketing brief used
// to live here as `video_brief`; it now rides the generative-UI channel via push_ui_message.)
export interface NoraAdditionalKwargs {
  tool_trace?: ToolTraceStep[];
  // Fallback chain-of-thought location: Anthropic surfaces reasoning as `thinking` content blocks
  // (handled in getReasoningString), but some providers (e.g. DeepSeek) stash it here instead.
  reasoning_content?: string;
}

// Payload emitted by the marketing human_review node's interrupt().
export interface ReviewInterrupt {
  kind?: "script_review";
  question: string;
  script_beats: ScriptBeat[];
}

// What we send back on resume (read by human_review in nodes.py).
export interface ReviewDecision {
  approved: boolean;
  edited_script?: ScriptBeat[];
}

// Payload emitted by the marketing choose_concept node's interrupt (the concept-pick gate).
export interface ConceptPickInterrupt {
  kind: "concept_pick";
  question: string;
  concepts: ConceptIdea[];
}

// Either marketing interrupt — distinguished by `kind` (concept_pick has no script_beats).
export type MarketingInterrupt = ReviewInterrupt | ConceptPickInterrupt;

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

export interface ChartPoint {
  label: string;
  value: number;
}

// The chart the analytics builder model chose for this answer (mirrors DashboardChart in
// schemas.py). `kind: "none"` (or an empty series) renders no chart.
export interface DashboardChart {
  kind: "bar" | "line" | "pie" | "none";
  x_label?: string | null;
  y_label?: string | null;
  series: ChartPoint[];
}

export interface AnalyticsDashboardData {
  title: string;
  stats: DashboardStat[];
  table?: DashboardTable | null;
  chart?: DashboardChart | null;
}

// The LLM-authored A2UI surface (mirrors A2uiSurface in schemas.py): an ordered list of catalog
// blocks the model composes per query. Rendered inline on /ask by A2uiSurfaceView when the "Author
// UI" output mode is on (ui_mode="authored"). One flat block shape (not a discriminated union) —
// `type` selects which fields are populated — matching the backend (which flattens to dodge
// OpenAI strict structured-output's union limits).
export interface A2uiMetric {
  label: string;
  value: string;
  trend?: "up" | "down" | "neutral" | null;
  trend_value?: string | null;
}
export interface A2uiBlock {
  type: "heading" | "text" | "metrics" | "chart" | "table";
  text?: string | null; // heading / text
  metrics?: A2uiMetric[] | null; // metrics
  title?: string | null; // chart
  chart_kind?: "bar" | "line" | "pie" | null; // chart
  series?: ChartPoint[] | null; // chart
  columns?: string[] | null; // table
  rows?: string[][] | null; // table
}
export interface A2uiSurface {
  blocks: A2uiBlock[];
}

// The marketing render result (mirrors RenderResult/RenderShot in schemas.py), pushed as the
// `marketing_render` card by the OpenRouter renderer. Stills (`image_url`) are served by the
// ops-api at /media (prefix with OPS_API_URL); videos are async OpenRouter jobs the card polls via
// the /api/render/video proxy until `video_job_id` completes, then streams the result.
export interface RenderShot {
  index: number;
  scene_description: string;
  t2v_prompt: string;
  image_url?: string | null;
  video_job_id?: string | null;
  error?: string | null;
}

export interface RenderResult {
  status: "placeholder" | "rendering" | "rendered" | "cancelled" | "error";
  mode: "image_to_video" | "text_to_video" | "none";
  hero_image_url?: string | null;
  shots: RenderShot[];
  image_model?: string | null;
  video_model?: string | null;
  detail: string;
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
