"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, Clapperboard, Film, Loader2 } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { OPS_API_URL } from "@/lib/config";
import type { RenderResult, RenderShot } from "@/lib/types";

// The marketing_render generative-UI card: the OpenRouter renderer's output. Stills come back
// immediately (served by the ops-api at /media); each shot's video is an async OpenRouter job, so
// the tile polls /api/render/video/{id} and swaps the still for a <video> once it completes.
const TERMINAL = new Set(["completed", "failed", "cancelled", "expired"]);
const POLL_MS = 6000;
// Stable empty default so an absent `shots` prop doesn't allocate a fresh [] each render (preserves
// referential equality for memoized children / dependency arrays).
const EMPTY_SHOTS: RenderShot[] = [];

function mediaUrl(path?: string | null): string | undefined {
  return path ? `${OPS_API_URL}${path}` : undefined;
}

export function MarketingRenderCard({
  status,
  mode,
  hero_image_url,
  shots = EMPTY_SHOTS,
  image_model,
  video_model,
  detail,
}: RenderResult) {
  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Clapperboard className="size-4 text-muted-foreground" />
          Generated ad
          <span className="rounded-full border bg-muted/40 px-2 py-px text-[10px] font-medium text-muted-foreground">
            {mode === "image_to_video" ? "image → video" : "text → video"}
          </span>
        </CardTitle>
        {detail ? <p className="text-xs text-muted-foreground">{detail}</p> : null}
      </CardHeader>

      <CardContent className="space-y-4">
        {hero_image_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- dynamic ops-api/proxy media; next/image's optimizer doesn't fit arbitrary runtime origins
          <img
            src={mediaUrl(hero_image_url)}
            alt="Generated ad hero frame"
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

        {(image_model || video_model) && (
          <p className="text-[11px] text-muted-foreground">
            {image_model ? `images: ${image_model}` : ""}
            {image_model && video_model ? " · " : ""}
            {video_model ? `video: ${video_model}` : ""}
          </p>
        )}
        {status === "error" ? (
          <p className="flex items-center gap-1.5 text-xs text-destructive">
            <AlertTriangle className="size-3.5" /> Some assets failed to generate.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ShotTile({ shot }: { shot: RenderShot }) {
  const still = mediaUrl(shot.image_url);
  const jobId = shot.video_job_id ?? null;
  const [videoStatus, setVideoStatus] = useState<string>(jobId ? "pending" : "none");

  useEffect(() => {
    if (!jobId) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const res = await fetch(`/api/render/video/${jobId}`, { cache: "no-store" });
        if (res.ok) {
          const data = (await res.json()) as { status?: string };
          if (active && data.status) {
            setVideoStatus(data.status);
            if (TERMINAL.has(data.status)) return; // stop scheduling on a terminal state
          }
        }
      } catch {
        /* transient network error — keep polling */
      }
      if (active) timer = setTimeout(poll, POLL_MS);
    };
    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [jobId]);

  const ready = videoStatus === "completed";
  const failed = videoStatus === "failed" || videoStatus === "cancelled" || videoStatus === "expired";

  return (
    <figure className="w-44 shrink-0 space-y-1.5">
      <div className="flex items-center justify-between text-[11px] font-medium text-muted-foreground">
        <span>Shot {shot.index + 1}</span>
        {jobId && !ready && !failed ? (
          <span className="flex items-center gap-1">
            <Loader2 className="size-3 animate-spin" /> rendering
          </span>
        ) : ready ? (
          <span className="flex items-center gap-1 text-emerald-600">
            <Film className="size-3" /> video
          </span>
        ) : null}
      </div>

      {ready && jobId ? (
        <video
          controls
          playsInline
          poster={still}
          src={`/api/render/video/${jobId}/content`}
          aria-label={`Generated video — shot ${shot.index + 1}`}
          className="aspect-[9/16] w-full rounded-md border object-cover"
        />
      ) : still ? (
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
        {shot.error ? (
          <span className="text-destructive">{shot.error}</span>
        ) : (
          shot.scene_description
        )}
      </figcaption>
    </figure>
  );
}
