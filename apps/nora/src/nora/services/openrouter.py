"""A thin OpenRouter client for image generation — the only place that talks to OpenRouter.

**Images** are synchronous: `POST /images` returns the bytes inline (base64 `data[].b64_json`).

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
    """The image-generation surface the renderer depends on (so tests can inject a fake)."""

    def generate_image(self, *, model: str, prompt: str, aspect_ratio: str) -> bytes:
        """Generate one image; return the raw image bytes. Raises on API error."""
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
                # NOTE: HTTP header values must be latin-1/ASCII-safe — keep this ASCII (an em-dash
                # here raised UnicodeEncodeError on the first real request).
                "HTTP-Referer": "https://github.com/curry-nomad",
                "X-Title": "Curry Nomad - Nora",
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

    def close(self) -> None:
        self._client.close()
