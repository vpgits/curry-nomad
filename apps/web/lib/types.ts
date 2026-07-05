// Mirrors the Pydantic contracts in apps/nora/src/nora/schemas.py (the marketing PostBrief),
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

export interface Critique {
  passed: boolean;
  issues: string[];
  suggestions: string[];
}

export interface Shot {
  index: number;
  scene_description: string;
  on_screen_text?: string | null;
}

export interface ShotPrompt {
  index: number;
  image_prompt: string;
}

export interface PostBrief {
  product_name: string;
  concept: string;
  hook: string;
  caption: string;
  shots: Shot[];
  shot_prompts: ShotPrompt[];
  cta: string;
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
// to live here as `post_brief`; it now rides the generative-UI channel via push_ui_message.)
export interface NoraAdditionalKwargs {
  tool_trace?: ToolTraceStep[];
  // Fallback chain-of-thought location: Anthropic surfaces reasoning as `thinking` content blocks
  // (handled in getReasoningString), but some providers (e.g. DeepSeek) stash it here instead.
  reasoning_content?: string;
}

// Payload emitted by the marketing human_review node's interrupt() — the post-copy review gate.
export type Verbosity = "concise" | "standard" | "detailed";

export interface ReviewInterrupt {
  kind?: "copy_review";
  question: string;
  caption: string;
  on_screen_texts: string[];
  num_images: number; // seeds the copy-gate stepper (1–8)
  verbosity: Verbosity; // seeds the copy-gate verbosity control
}

// What we send back on resume (read by human_review in nodes.py). `regenerate` re-runs write_copy
// with the operator's `num_images`/`verbosity` (cheap — images render after approval).
export interface ReviewDecision {
  approved?: boolean;
  edited_copy?: { caption: string; on_screen_texts: string[] };
  regenerate?: boolean;
  num_images?: number;
  verbosity?: Verbosity;
}

// Payload emitted by the marketing choose_concept node's interrupt (the concept-pick gate).
export interface ConceptPickInterrupt {
  kind: "concept_pick";
  question: string;
  concepts: ConceptIdea[];
}

// Payload emitted by the marketing still_review node's interrupt (the visual gate). The operator
// approves the generated stills — or asks to re-roll specific shots — before the Instagram post is
// finalized. `index: -1` targets the hero image.
export interface StillReviewShot {
  index: number;
  image_url: string | null;
  scene_description: string | null;
}
export interface StillReviewInterrupt {
  kind: "still_review";
  question: string;
  hero_image_url: string | null;
  shots: StillReviewShot[];
}

// What we send back on resume (read by still_review in nodes.py): approve, or regenerate the listed
// shot indices (with optional per-shot prompt overrides).
export interface StillDecision {
  approved?: boolean;
  regenerate?: number[];
  prompt_overrides?: Record<number, string>;
}

// The marketing interrupts — distinguished by `kind` (concept_pick carries concepts; copy_review
// carries the caption; still_review carries stills).
export type MarketingInterrupt = ReviewInterrupt | ConceptPickInterrupt | StillReviewInterrupt;

// One pending write the workspace agent wants to run (send/create/…), awaiting human approval. Both
// HITL backends expose `name` + `args` (the installed HumanInTheLoopMiddleware uses `args`, same key
// as the hand-written gate); `arguments` is tolerated as a fallback. `id` is present on path B only.
// One field of the AI-authored approval card: the model picked the label/order; the `value` is the
// LITERAL tool arg (filled by the backend, never paraphrased). `block` = long text (e.g. an email body).
export interface ApprovalLayoutField {
  label: string;
  value: string;
  style: "inline" | "block";
}

// The AI-authored layout for an approval card (primitive HITL path). Absent on the middleware path /
// when there's no model — the web client then builds a literal fallback from the args.
export interface ApprovalLayout {
  icon: "email" | "calendar" | "document" | "generic";
  title: string;
  fields: ApprovalLayoutField[];
}

export interface WorkspaceActionRequest {
  name: string;
  args?: Record<string, unknown>;
  arguments?: Record<string, unknown>;
  id?: string;
  description?: string;
  layout?: ApprovalLayout; // AI-authored presentation (values literal); fallback derived if absent
}

// Payload emitted when an agent pauses before WRITE actions — the shared write-approval gate. Covers:
//   - the workspace agent (Gmail/Sheets/Docs/…): `kind: "workspace_approval"` (primitive), or the
//     middleware path which adds `review_configs` and no kind.
//   - the operations agent (high-risk order/stock/customer writes): `kind: "operations_approval"`.
// All carry the same `action_requests` shape and resume the same way, so one gate component drives them.
export interface WorkspaceApprovalInterrupt {
  kind?: "workspace_approval" | "operations_approval";
  question?: string;
  action_requests: WorkspaceActionRequest[];
  review_configs?: unknown[];
}

// One decision sent back on resume (read by the gate node / middleware), one per action in order.
export interface WorkspaceDecision {
  type: "approve" | "edit" | "reject";
  edited_action?: { name: string; args: Record<string, unknown> };
  message?: string;
}

// Any interrupt the thread might surface. The workspace gate is detected by `action_requests`
// (present on both its backends, absent on the marketing gates) — see isWorkspaceApproval.
export type ThreadInterrupt = MarketingInterrupt | WorkspaceApprovalInterrupt;

// Discriminator: a workspace write-approval interrupt carries an `action_requests` array (the
// marketing concept_pick/copy_review gates never do). Check this BEFORE casting to MarketingInterrupt.
export function isWorkspaceApproval(value: unknown): value is WorkspaceApprovalInterrupt {
  return (
    typeof value === "object" &&
    value !== null &&
    Array.isArray((value as { action_requests?: unknown }).action_requests)
  );
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
export interface A2uiField {
  label: string;
  value: string;
}
export interface A2uiBlock {
  type: "heading" | "text" | "metrics" | "fields" | "chart" | "table";
  text?: string | null; // heading / text
  metrics?: A2uiMetric[] | null; // metrics
  fields?: A2uiField[] | null; // fields (label→value detail rows for one record/entity)
  title?: string | null; // chart / optional title above a fields or table block
  chart_kind?: "bar" | "line" | "pie" | null; // chart
  series?: ChartPoint[] | null; // chart
  columns?: string[] | null; // table
  rows?: string[][] | null; // table
}
export interface A2uiSurface {
  blocks: A2uiBlock[];
}

// The marketing render result (mirrors RenderResult/RenderShot in schemas.py), pushed as the
// `marketing_render` card by the OpenRouter renderer — the hero image + a still per shot that make
// up the Instagram post. Stills (`image_url`) are served by the ops-api at /media (prefix with
// OPS_API_URL).
export interface RenderShot {
  index: number;
  scene_description: string;
  image_prompt: string;
  image_url?: string | null;
  error?: string | null;
}

export interface RenderResult {
  status: "placeholder" | "stills_ready" | "rendered" | "cancelled" | "error";
  hero_image_url?: string | null;
  shots: RenderShot[];
  image_model?: string | null;
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
