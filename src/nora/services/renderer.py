"""Render adapters for the finished VideoBrief.

By default the workflow does NOT call any external video API — `PlaceholderRenderer` returns
the per-shot prompts as a stub so the demo runs offline with zero spend. `OpenRouterRenderer`
is a documented stub for M7: it would POST each shot's `t2v_prompt` to an OpenRouter video
model and return an asset reference. Selecting between them is a one-line config change
(`NORA_RENDERER`), which is the ports-&-adapters lesson.
"""

from __future__ import annotations

from nora.config import Settings
from nora.observability import get_logger
from nora.schemas import VideoBrief

log = get_logger(__name__)


class PlaceholderRenderer:
    """Default renderer: no external calls. Logs the shot prompts and returns a stub."""

    def render(self, brief: VideoBrief) -> dict:
        log.info(
            "render.placeholder",
            product=brief.product_name,
            shots=len(brief.shot_prompts),
        )
        return {
            "status": "placeholder",
            "asset_ref": None,
            "detail": "render skipped; prompts ready",
        }


class OpenRouterRenderer:
    """Real text-to-video renderer (stub/TODO for M7).

    When implemented this will, for each `ShotPrompt`, POST `t2v_prompt` to
    `settings.openrouter_video_model` using `settings.openrouter_api_key`, collect/stitch the
    returned clips, and return ``{"status": "rendered", "asset_ref": <url>, "detail": ...}``.

    ⚠️ verify OpenRouter's current text-to-video API surface before implementing.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def render(self, brief: VideoBrief) -> dict:
        raise NotImplementedError(
            "OpenRouterRenderer is a stub. Implement in M7: POST each shot's t2v_prompt to "
            "settings.openrouter_video_model and return an asset_ref. "
            "Set NORA_RENDERER=placeholder to run the demo offline."
        )


def get_renderer(settings: Settings):
    """Factory: select the renderer adapter by `settings.renderer`."""
    if settings.renderer == "openrouter":
        return OpenRouterRenderer(settings)
    return PlaceholderRenderer()
