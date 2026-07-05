"""Render adapters for the finished PostBrief.

By default the workflow does NOT call any external image API — `PlaceholderRenderer` returns a
stub so the demo runs offline with zero spend. `OpenRouterRenderer` is the real adapter: it
generates a hero image + a per-shot still (synchronously, via OpenRouter `/images`) that together
make up the finished **Instagram post**.

**Staged rendering (so a human can review the images first).** Rendering is split so a review gate
can sit between generating the stills and finalizing the post:

1. `render_stills(brief)` — generate the hero image and a per-shot still via OpenRouter `/images`.
2. (optional) `regenerate_stills(brief, stills, indices, overrides)` — re-roll the stills the
   operator rejected, reusing the same media dir; loops back to review.

Selecting the adapter is a one-line config change (`NORA_RENDERER`), the ports-&-adapters lesson.
The stills are written to `settings.media_dir`, served by the ops-api at `/media`, and ride the
`render_result` into the `marketing_render` card.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from nora.config import Settings
from nora.observability import get_logger
from nora.schemas import PostBrief, RenderResult, RenderShot
from nora.services.openrouter import HttpOpenRouterClient, OpenRouterClient

log = get_logger(__name__)


class PlaceholderRenderer:
    """Default renderer: no external calls. Logs the shot prompts and returns a stub. The staged
    methods all collapse to the same placeholder stub, so the marketing graph's still-review gate
    finds nothing to review and passes straight through (no interrupt, no spend)."""

    def _stub(self) -> dict:
        return RenderResult(
            status="placeholder",
            detail="render skipped; prompts ready (set NORA_RENDERER=openrouter to generate images)",
        ).model_dump()

    def render_stills(self, brief: PostBrief) -> dict:
        log.info("render.placeholder", product=brief.product_name, shots=len(brief.shot_prompts))
        return self._stub()

    def regenerate_stills(
        self, brief: PostBrief, stills: dict, indices: list[int], prompt_overrides: dict[int, str]
    ) -> dict:
        return stills or self._stub()


class OpenRouterRenderer:
    """Real image renderer over OpenRouter. The client is injectable so tests run fully offline.

    Construction is **lazy**: it never builds the HTTP client (or requires a key) up front, so the
    marketing graph can be built — and non-rendering turns can run — without an OPENROUTER_API_KEY.
    The key is required only when a render step actually runs (it raises loudly there if missing);
    the marketing render nodes catch that and record it as an error result, so the brief still ships."""

    def __init__(self, settings: Settings, *, client: OpenRouterClient | None = None):
        self.settings = settings
        self._client = client  # None → built on first use from the key (raises there if missing)

    @property
    def client(self) -> OpenRouterClient:
        if self._client is None:
            if not self.settings.openrouter_api_key:
                raise ValueError(
                    "OpenRouterRenderer needs an OPENROUTER_API_KEY (or an injected client) to "
                    "render media. Set NORA_RENDERER=placeholder to run without rendering."
                )
            self._client = HttpOpenRouterClient(
                api_key=self.settings.openrouter_api_key, base_url=self.settings.openrouter_base_url
            )
        return self._client

    def _hero_prompt(self, brief: PostBrief) -> str:
        return (
            f"Advertising hero image for {brief.product_name}. Concept: {brief.concept}. "
            f"Hook: {brief.hook}. Vibrant, appetising, vertical composition for a social post."
        )

    def _save_image(self, out_dir: Path, render_id: str, name: str, prompt: str) -> str | None:
        """Generate + persist one image; return its served (relative) /media path, or None."""
        try:
            data = self.client.generate_image(
                model=self.settings.openrouter_image_model,
                prompt=prompt,
                aspect_ratio=self.settings.render_aspect_ratio,
            )
        except Exception as exc:  # noqa: BLE001 — per-asset best-effort; one failure ≠ whole render
            log.info("render.image.error", name=name, error=str(exc))
            return None
        (out_dir / f"{name}.png").write_bytes(data)
        return f"/media/{render_id}/{name}.png"

    def render_stills(self, brief: PostBrief) -> dict:
        """Generate the hero + per-shot stills that make up the Instagram post."""
        s = self.settings
        client = self.client  # resolve up front so a missing key fails loudly here
        assert client is not None  # for type-checkers; the property raises otherwise
        render_id = uuid.uuid4().hex[:12]
        out_dir = Path(s.media_dir) / render_id
        out_dir.mkdir(parents=True, exist_ok=True)

        hero_url = self._save_image(out_dir, render_id, "hero", self._hero_prompt(brief))
        prompt_by_index = {sp.index: sp.image_prompt for sp in brief.shot_prompts}
        shots = sorted(brief.shots, key=lambda sh: sh.index)[: s.render_max_shots]

        rendered: list[RenderShot] = []
        for shot in shots:
            prompt = prompt_by_index.get(shot.index) or shot.scene_description
            image_url = self._save_image(out_dir, render_id, f"shot-{shot.index}", prompt)
            rendered.append(
                RenderShot(
                    index=shot.index,
                    scene_description=shot.scene_description,
                    image_prompt=prompt,
                    image_url=image_url,
                )
            )
        ready = sum(1 for r in rendered if r.image_url)
        log.info("render.stills", product=brief.product_name, ready=ready)
        return RenderResult(
            status="stills_ready",
            hero_image_url=hero_url,
            shots=rendered,
            image_model=s.openrouter_image_model,
            render_id=render_id,
            detail=f"{ready}/{len(rendered)} images ready; review before finalizing the post.",
        ).model_dump()

    def regenerate_stills(
        self, brief: PostBrief, stills: dict, indices: list[int], prompt_overrides: dict[int, str]
    ) -> dict:
        """Re-roll only the flagged shots (index -1 = the hero), reusing the prior result's media
        dir so untouched stills are preserved. Returns the updated stills result."""
        s = self.settings
        _ = self.client  # resolve/raise on missing key before touching disk
        result = RenderResult(**stills)
        want = set(indices)
        # Reuse the existing media dir (so kept stills stay valid); fall back to a fresh one.
        render_id = result.render_id or uuid.uuid4().hex[:12]
        out_dir = Path(s.media_dir) / render_id
        out_dir.mkdir(parents=True, exist_ok=True)
        overrides = {int(k): v for k, v in (prompt_overrides or {}).items()}

        if -1 in want:
            result.hero_image_url = (
                self._save_image(out_dir, render_id, "hero", self._hero_prompt(brief))
                or result.hero_image_url
            )
        for shot in result.shots:
            if shot.index in want:
                prompt = overrides.get(shot.index) or shot.image_prompt
                new_url = self._save_image(out_dir, render_id, f"shot-{shot.index}", prompt)
                if new_url:
                    shot.image_url, shot.image_prompt, shot.error = new_url, prompt, None
        result.render_id = render_id
        log.info("render.stills.regenerate", product=brief.product_name, shots=sorted(want))
        return result.model_dump()


def get_renderer(settings: Settings):
    """Factory: select the renderer adapter by `settings.renderer`."""
    if settings.renderer == "openrouter":
        return OpenRouterRenderer(settings)
    return PlaceholderRenderer()
