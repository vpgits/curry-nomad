"use client";

import { Clapperboard, Film, Hash, Megaphone, Music2, Quote } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import type { VideoBrief } from "@/lib/types";

// Renders the final creative package the marketing workflow produces.
export function VideoBriefCard({ brief }: { brief: VideoBrief }) {
  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Clapperboard className="size-4 text-muted-foreground" />
          Video brief — {brief.product_name}
        </CardTitle>
        <CardDescription>
          {brief.concept} · ~{Math.round(brief.target_duration_s)}s · {brief.platform}
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
          <Stat label="Hook" value={brief.hook} />
          <Stat label="Call to action" value={brief.cta} icon={<Megaphone className="size-3" />} />
          <Stat label="Music mood" value={brief.music_mood} icon={<Music2 className="size-3" />} />
          <Stat
            label="Shots"
            value={`${brief.shots.length} shots · ${brief.shot_prompts.length} prompts`}
          />
        </div>

        <Separator />

        <section className="space-y-2">
          <SectionTitle icon={<Film className="size-3.5" />}>Script</SectionTitle>
          <div className="space-y-2">
            {brief.script_beats.map((b) => (
              <div key={b.t_start_s} className="border-l-2 border-border pl-3">
                <div className="font-mono text-xs text-muted-foreground">
                  {b.t_start_s}s – {b.t_end_s}s
                </div>
                <p className="text-sm leading-relaxed">{b.voiceover}</p>
              </div>
            ))}
          </div>
        </section>

        <Separator />

        <section className="space-y-2">
          <SectionTitle icon={<Quote className="size-3.5" />}>Grounded in</SectionTitle>
          <div className="flex flex-wrap gap-1.5">
            {brief.product_facts_used.map((f) => (
              <Badge key={f} variant="secondary" className="font-normal">
                {f}
              </Badge>
            ))}
          </div>
        </section>

        <section className="space-y-2">
          <SectionTitle icon={<Hash className="size-3.5" />}>Hashtags</SectionTitle>
          <div className="flex flex-wrap gap-1.5">
            {brief.hashtags.map((h) => (
              <Badge key={h} variant="outline">
                {h}
              </Badge>
            ))}
          </div>
        </section>
      </CardContent>
    </Card>
  );
}

function Stat({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">
        {icon}
        {label}
      </div>
      <p className="text-sm leading-relaxed">{value}</p>
    </div>
  );
}

function SectionTitle({
  children,
  icon,
}: {
  children: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-1.5 text-xs font-medium tracking-wide text-muted-foreground uppercase">
      {icon}
      {children}
    </div>
  );
}
