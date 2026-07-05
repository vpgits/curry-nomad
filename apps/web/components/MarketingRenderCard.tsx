"use client";

import { AlertTriangle, Image as ImageIcon } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { OPS_API_URL } from "@/lib/config";
import type { RenderResult, RenderShot } from "@/lib/types";

// The marketing_render generative-UI card: the OpenRouter renderer's output — the hero image + a
// still per shot that make up the finished Instagram post (served by the ops-api at /media).
// Stable empty default so an absent `shots` prop doesn't allocate a fresh [] each render.
const EMPTY_SHOTS: RenderShot[] = [];

function mediaUrl(path?: string | null): string | undefined {
  return path ? `${OPS_API_URL}${path}` : undefined;
}

export function MarketingRenderCard({
  status,
  hero_image_url,
  shots = EMPTY_SHOTS,
  image_model,
  detail,
}: RenderResult) {
  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <ImageIcon className="size-4 text-muted-foreground" />
          Instagram post
        </CardTitle>
        {detail ? <p className="text-xs text-muted-foreground">{detail}</p> : null}
      </CardHeader>

      <CardContent className="space-y-4">
        {hero_image_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- dynamic ops-api media; next/image's optimizer doesn't fit arbitrary runtime origins
          <img
            src={mediaUrl(hero_image_url)}
            alt="Generated post hero image"
            className="aspect-[9/16] max-h-72 w-auto rounded-lg border object-cover"
          />
        ) : null}

        {shots.length ? (
          <div className="flex gap-3 overflow-x-auto pb-2">
            {shots.map((shot) => (
              <ShotTile key={shot.index} shot={shot} />
            ))}
          </div>
        ) : null}

        {image_model ? (
          <p className="text-[11px] text-muted-foreground">images: {image_model}</p>
        ) : null}
        {status === "error" ? (
          <p className="flex items-center gap-1.5 text-xs text-destructive">
            <AlertTriangle className="size-3.5" /> Some images failed to generate.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ShotTile({ shot }: { shot: RenderShot }) {
  const still = mediaUrl(shot.image_url);
  return (
    <figure className="w-44 shrink-0 space-y-1.5">
      <div className="text-[11px] font-medium text-muted-foreground">Image {shot.index + 1}</div>
      {still ? (
        // eslint-disable-next-line @next/next/no-img-element -- dynamic ops-api media; next/image's optimizer doesn't fit arbitrary runtime origins
        <img
          src={still}
          alt={shot.scene_description}
          className="aspect-[9/16] w-full rounded-md border object-cover"
        />
      ) : (
        <div className="aspect-[9/16] w-full rounded-md border border-dashed bg-gradient-to-br from-muted to-accent/30" />
      )}
      <figcaption className="line-clamp-2 text-[12px] leading-snug">
        {shot.error ? <span className="text-destructive">{shot.error}</span> : shot.scene_description}
      </figcaption>
    </figure>
  );
}
