"""A thin OpenRouter client for media generation — the only place that talks to OpenRouter.

Two surfaces, two shapes (per OpenRouter's API):

- **Images** are synchronous: `POST /images` returns the bytes inline (base64 `data[].b64_json`).
- **Videos** are asynchronous jobs: `POST /videos` returns `{id, status, polling_url}`; you poll
  `GET /videos/{id}` until `completed`, then download from `unsigned_urls` / `…/content`. This
  client only *submits* (the web UI does the polling), but `get_video` is here for completeness and
  for the offline tests.

Kept deliberately small and provider-specific: this is an adapter behind the `Renderer` port, not a
general model layer, so unlike the chat/embedding models (built via `init_chat_model`) it is a plain
httpx client. It is only ever constructed when `NORA_RENDERER=openrouter`, and is injectable so the
renderer's tests run fully offline against a fake.
"""

from __future__ import annotations

import base64
from typing import Protocol, runtime_checkable

import httpx

from nora.observability import get_logger

log = get_logger(__name__)


@runtime_checkable
class OpenRouterClient(Protocol):
    """The media-generation surface the renderer depends on (so tests can inject a fake)."""

    def generate_image(self, *, model: str, prompt: str, aspect_ratio: str) -> bytes:
        """Generate one image; return the raw image bytes. Raises on API error."""
        ...

    def submit_video(
        self,
        *,
        model: str,
        prompt: str,
        first_frame_url: str | None,
        duration_s: int,
        resolution: str,
        aspect_ratio: str,
        generate_audio: bool,
    ) -> dict:
        """Submit a video job; return `{id, status, polling_url}`. If `first_frame_url` is given the
        request is image→video (first-frame conditioned); otherwise text→video."""
        ...

    def get_video(self, job_id: str) -> dict:
        """Poll a job; return `{id, status, polling_url, unsigned_urls?}`."""
        ...


class HttpOpenRouterClient:
    """Concrete `OpenRouterClient` over httpx. Constructed only with a real API key."""

    def __init__(self, *, api_key: str, base_url: str, timeout_s: float = 60.0):
        self._base = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self._base,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                # Optional attribution headers OpenRouter recommends; harmless if ignored.
                "HTTP-Referer": "https://github.com/curry-nomad",
                "X-Title": "Curry Nomad — Nora",
            },
            timeout=timeout_s,
        )

    def generate_image(self, *, model: str, prompt: str, aspect_ratio: str) -> bytes:
        resp = self._client.post(
            "/images",
            json={"model": model, "prompt": prompt, "aspect_ratio": aspect_ratio, "n": 1},
        )
        resp.raise_for_status()
        data = resp.json()
        b64 = data["data"][0]["b64_json"]
        log.info("render.image", model=model, cost=data.get("usage", {}).get("cost"))
        return base64.b64decode(b64)

    def submit_video(
        self,
        *,
        model: str,
        prompt: str,
        first_frame_url: str | None,
        duration_s: int,
        resolution: str,
        aspect_ratio: str,
        generate_audio: bool,
    ) -> dict:
        body: dict = {
            "model": model,
            "prompt": prompt,
            "duration": duration_s,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "generate_audio": generate_audio,
        }
        if first_frame_url:
            # Presence of frame_images → OpenRouter treats this as image→video (first-frame conditioned).
            body["frame_images"] = [
                {
                    "type": "image_url",
                    "image_url": {"url": first_frame_url},
                    "frame_type": "first_frame",
                }
            ]
        resp = self._client.post("/videos", json=body)
        resp.raise_for_status()
        job = resp.json()
        log.info("render.video.submit", model=model, job=job.get("id"), status=job.get("status"))
        return job

    def get_video(self, job_id: str) -> dict:
        resp = self._client.get(f"/videos/{job_id}")
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        self._client.close()
