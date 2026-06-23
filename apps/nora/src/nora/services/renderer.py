"""Render adapters for the finished VideoBrief.

By default the workflow does NOT call any external video API — `PlaceholderRenderer` returns a
stub so the demo runs offline with zero spend. `OpenRouterRenderer` is the real adapter: it
generates a hero image and a per-shot still (synchronously, via OpenRouter `/images`), then
submits one image→video job per shot (via `/videos`) and returns their job ids for the UI to poll.
Selecting between them is a one-line config change (`NORA_RENDERER`), which is the ports-&-adapters
lesson.

**Why the renderer only submits video jobs (and the UI polls):** video generation takes minutes, so
blocking the chat turn on it is poor UX. Images come back inline; videos are kicked off and their
job ids ride the `render_result` into the `marketing_render` card, which polls each one.

**The image→video first-frame constraint:** OpenRouter fetches the first-frame image from a *public*
URL — it cannot reach a `localhost` media server. So image→video is used only when
`settings.media_public_base_url` is configured; otherwise the renderer falls back to text→video
(still per-shot video, just not first-frame-conditioned) and records that in the result `mode`.
Either way the stills are written locally and shown in the card.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from nora.config import Settings
from nora.observability import get_logger
from nora.schemas import RenderResult, RenderShot, VideoBrief
from nora.services.openrouter import HttpOpenRouterClient, OpenRouterClient

log = get_logger(__name__)


class PlaceholderRenderer:
    """Default renderer: no external calls. Logs the shot prompts and returns a stub."""

    def render(self, brief: VideoBrief) -> dict:
        log.info("render.placeholder", product=brief.product_name, shots=len(brief.shot_prompts))
        return RenderResult(
            status="placeholder",
            mode="none",
            detail="render skipped; prompts ready (set NORA_RENDERER=openrouter to generate media)",
        ).model_dump()


class OpenRouterRenderer:
    """Real media renderer over OpenRouter. The client is injectable so tests run fully offline."""

    def __init__(self, settings: Settings, *, client: OpenRouterClient | None = None):
        self.settings = settings
        if client is None:
            if not settings.openrouter_api_key:
                raise ValueError(
                    "OpenRouterRenderer needs an OPENROUTER_API_KEY (or an injected client). "
                    "Set NORA_RENDERER=placeholder to run offline."
                )
            client = HttpOpenRouterClient(
                api_key=settings.openrouter_api_key, base_url=settings.openrouter_base_url
            )
        self.client = client

    def _hero_prompt(self, brief: VideoBrief) -> str:
        return (
            f"Advertising hero image for {brief.product_name}. Concept: {brief.concept}. "
            f"Hook: {brief.hook}. Vibrant, appetising, vertical composition for a social reel."
        )

    def render(self, brief: VideoBrief) -> dict:
        s = self.settings
        media_dir = Path(s.media_dir)
        render_id = uuid.uuid4().hex[:12]
        out_dir = media_dir / render_id
        out_dir.mkdir(parents=True, exist_ok=True)

        # image→video needs a public first-frame URL OpenRouter can fetch; otherwise text→video.
        public_base = (s.media_public_base_url or "").rstrip("/") or None
        mode = "image_to_video" if public_base else "text_to_video"

        def save_image(name: str, prompt: str) -> str | None:
            """Generate + persist one image; return its served (relative) /media path, or None."""
            try:
                data = self.client.generate_image(
                    model=s.openrouter_image_model, prompt=prompt, aspect_ratio=s.render_aspect_ratio
                )
            except Exception as exc:  # noqa: BLE001 — per-asset best-effort; one failure ≠ whole render
                log.info("render.image.error", name=name, error=str(exc))
                return None
            path = out_dir / f"{name}.png"
            path.write_bytes(data)
            return f"/media/{render_id}/{name}.png"

        hero_url = save_image("hero", self._hero_prompt(brief))

        # Pair each shot with its t2v_prompt; render up to render_max_shots (cost guard).
        prompt_by_index = {sp.index: sp.t2v_prompt for sp in brief.shot_prompts}
        shots = sorted(brief.shots, key=lambda sh: sh.index)[: s.render_max_shots]

        rendered: list[RenderShot] = []
        for shot in shots:
            t2v = prompt_by_index.get(shot.index) or shot.scene_description
            image_url = save_image(f"shot-{shot.index}", t2v)
            first_frame = f"{public_base}{image_url}" if (public_base and image_url) else None
            job_id: str | None = None
            err: str | None = None
            try:
                job = self.client.submit_video(
                    model=s.openrouter_video_model,
                    prompt=t2v,
                    first_frame_url=first_frame,
                    duration_s=s.render_video_duration_s,
                    resolution=s.render_resolution,
                    aspect_ratio=s.render_aspect_ratio,
                    generate_audio=s.render_generate_audio,
                )
                job_id = job.get("id")
            except Exception as exc:  # noqa: BLE001 — per-shot best-effort
                err = str(exc)
                log.info("render.video.error", shot=shot.index, error=err)
            rendered.append(
                RenderShot(
                    index=shot.index,
                    scene_description=shot.scene_description,
                    t2v_prompt=t2v,
                    image_url=image_url,
                    video_job_id=job_id,
                    error=err,
                )
            )

        submitted = sum(1 for r in rendered if r.video_job_id)
        detail = (
            f"{submitted}/{len(rendered)} shot videos submitted ({mode}); "
            f"hero image {'ready' if hero_url else 'failed'}."
        )
        if mode == "text_to_video":
            detail += " Set NORA_MEDIA_PUBLIC_BASE_URL for first-frame (image→video) conditioning."
        log.info("render.openrouter", product=brief.product_name, submitted=submitted, mode=mode)
        return RenderResult(
            status="rendering" if submitted else "error",
            mode=mode,
            hero_image_url=hero_url,
            shots=rendered,
            image_model=s.openrouter_image_model,
            video_model=s.openrouter_video_model,
            detail=detail,
        ).model_dump()


def get_renderer(settings: Settings):
    """Factory: select the renderer adapter by `settings.renderer`."""
    if settings.renderer == "openrouter":
        return OpenRouterRenderer(settings)
    return PlaceholderRenderer()
