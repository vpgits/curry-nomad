// Mirrors the Pydantic contracts in src/nora/schemas.py (the marketing VideoBrief) and the
// human_review interrupt payload, so the UI can render them type-safely.

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

// Orchestrator graph state surfaced by useStream.
export interface NoraState {
  messages: unknown[];
}
