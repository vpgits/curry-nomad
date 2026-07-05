"""Foundation tests: config, observability, renderer adapters (M6 coverage top-up)."""

from __future__ import annotations

import json

import pytest

from nora.config import Settings, get_settings
from nora.observability import get_logger, setup_logging
from nora.schemas import PostBrief, Shot, ShotPrompt
from nora.services.renderer import OpenRouterRenderer, PlaceholderRenderer, get_renderer
from tests.fakes import FakeOpenRouterClient


def _brief() -> PostBrief:
    return PostBrief(
        product_name="Black Pepper",
        concept="bold",
        hook="Kandy heat",
        caption="Kandy heat.\nSingle-origin black pepper from the hills. Shop now.",
        shots=[Shot(index=0, scene_description="x", on_screen_text="Kandy heat")],
        shot_prompts=[ShotPrompt(index=0, image_prompt="x")],
        cta="Shop now",
        hashtags=["#CurryNomad"],
        product_facts_used=["Black Pepper", "origin: Kandy"],
    )


def test_settings_defaults():
    s = get_settings()
    assert s.model.startswith("openai:")
    assert s.router_model.startswith("openai:")
    assert s.data_as_of.isoformat() == "2026-06-30"
    assert s.db_path.name == "curry_nomad.db"
    assert s.embedding_dims == 1536
    # The offline suite pins renderer/workspace off (conftest), so check the SHIPPED field defaults
    # directly (env-independent): both capabilities are first-party now.
    assert Settings.model_fields["renderer"].default == "openrouter"
    assert Settings.model_fields["workspace_enabled"].default is True


def test_logging_emits_structured_json(capsys):
    setup_logging(json_logs=True)
    get_logger("test").info("hello_event", widget="spice")
    line = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "hello_event"
    assert record["widget"] == "spice"
    assert record["level"] == "info"


def test_offline_suite_pins_placeholder_renderer():
    # The shipped default is the OpenRouter renderer; the offline suite pins NORA_RENDERER=placeholder
    # (conftest) so no test makes a real external call without explicitly injecting a client.
    assert isinstance(get_renderer(get_settings()), PlaceholderRenderer)


def test_placeholder_render_makes_no_external_call():
    result = PlaceholderRenderer().render_stills(_brief())
    assert result["status"] == "placeholder"
    assert result["shots"] == []


def test_openrouter_renderer_generates_stills(tmp_path):
    # The real adapter (fake client) generates a hero + per-shot still for the Instagram post.
    settings = Settings(media_dir=tmp_path)
    client = FakeOpenRouterClient()
    result = OpenRouterRenderer(settings, client=client).render_stills(_brief())

    assert result["status"] == "stills_ready"
    assert result["hero_image_url"].startswith("/media/")
    assert len(result["shots"]) == 1
    assert result["shots"][0]["image_url"].startswith("/media/")
    # the image bytes were actually written under media_dir (hero + shots).
    assert client.image_calls and list(tmp_path.rglob("*.png"))


def test_openrouter_renderer_regenerate_reuses_media_dir(tmp_path):
    # Re-rolling reuses the same media sub-dir so untouched stills stay valid.
    settings = Settings(media_dir=tmp_path)
    client = FakeOpenRouterClient()
    renderer = OpenRouterRenderer(settings, client=client)
    stills = renderer.render_stills(_brief())
    before = len(client.image_calls)
    updated = renderer.regenerate_stills(_brief(), stills, [-1], {})  # -1 = hero, always re-generated
    assert len(client.image_calls) > before
    assert updated["render_id"] == stills["render_id"]


def test_openrouter_renderer_needs_a_key_or_client():
    # Hard-require, but lazy: construction is cheap (so building the marketing graph / running a
    # non-rendering turn needs no key); RENDERING without a key/client fails loudly.
    renderer = OpenRouterRenderer(Settings(openrouter_api_key=None))  # no raise at construction
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        renderer.render_stills(_brief())


def test_openrouter_client_headers_are_header_safe():
    # HTTP header values must be latin-1/ASCII-encodable. A non-ASCII char (an em-dash in X-Title)
    # only blows up on the first REAL request (UnicodeEncodeError), so it slipped through until real
    # rendering ran — pin every configured header to latin-1 here.
    from nora.services.openrouter import HttpOpenRouterClient

    client = HttpOpenRouterClient(api_key="test-key", base_url="https://example.com")
    for value in client._client.headers.values():
        value.encode("latin-1")  # raises UnicodeEncodeError if a header carries a non-latin-1 char
