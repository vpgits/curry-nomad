"use client";

import type { VideoBrief } from "@/lib/types";

// Renders the final creative package the marketing workflow produces.
export function VideoBriefCard({ brief }: { brief: VideoBrief }) {
  return (
    <div className="card brief">
      <h3>🎬 Video brief — {brief.product_name}</h3>
      <div className="sub">
        {brief.concept} · ~{Math.round(brief.target_duration_s)}s · {brief.platform}
      </div>

      <div className="grid">
        <div>
          <div className="label">Hook</div>
          {brief.hook}
        </div>
        <div>
          <div className="label">Call to action</div>
          {brief.cta}
        </div>
        <div>
          <div className="label">Music mood</div>
          {brief.music_mood}
        </div>
        <div>
          <div className="label">Shots</div>
          {brief.shots.length} ({brief.shot_prompts.length} prompts)
        </div>
      </div>

      <div className="section-title">Script</div>
      {brief.script_beats.map((b, i) => (
        <div className="beat" key={i}>
          <div className="t">
            {b.t_start_s}s – {b.t_end_s}s
          </div>
          <div>{b.voiceover}</div>
        </div>
      ))}

      <div className="section-title">Grounded in</div>
      <div className="tags">
        {brief.product_facts_used.map((f, i) => (
          <span className="tag" key={i}>
            {f}
          </span>
        ))}
      </div>

      <div className="section-title">Hashtags</div>
      <div className="tags">
        {brief.hashtags.map((h, i) => (
          <span className="tag" key={i}>
            {h}
          </span>
        ))}
      </div>
    </div>
  );
}
