"use client";

import { AlignLeft, Hash, Image as ImageIcon, Megaphone, Quote } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import type { PostBrief } from "@/lib/types";

// Renders the final creative package the marketing workflow produces — an Instagram image post.
export function PostBriefCard({ brief }: { brief: PostBrief }) {
  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <ImageIcon className="size-4 text-muted-foreground" />
          Instagram post — {brief.product_name}
        </CardTitle>
        <CardDescription>{brief.concept}</CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
          <Stat label="Hook" value={brief.hook} />
          <Stat label="Call to action" value={brief.cta} icon={<Megaphone className="size-3" />} />
          <Stat
            label="Images"
            value={`${brief.shots.length} images`}
            icon={<ImageIcon className="size-3" />}
          />
        </div>

        <Separator />

        <section className="space-y-2">
          <SectionTitle icon={<AlignLeft className="size-3.5" />}>Caption</SectionTitle>
          <p className="text-sm leading-relaxed whitespace-pre-line">{brief.caption}</p>
        </section>

        {brief.shots.some((s) => s.on_screen_text) && (
          <>
            <Separator />
            <section className="space-y-2">
              <SectionTitle icon={<Quote className="size-3.5" />}>On-screen text</SectionTitle>
              <div className="space-y-2">
                {brief.shots.map((s) => (
                  <div key={s.index} className="border-l-2 border-border pl-3">
                    <div className="font-mono text-xs text-muted-foreground">
                      Image {s.index + 1}
                    </div>
                    <p className="text-sm leading-relaxed">
                      {s.on_screen_text || s.scene_description}
                    </p>
                  </div>
                ))}
              </div>
            </section>
          </>
        )}

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
