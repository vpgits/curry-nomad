"""Foundation tests: config, observability, renderer adapters (M6 coverage top-up)."""

from __future__ import annotations

import json

import pytest

from nora.config import Settings, get_settings
from nora.observability import get_logger, setup_logging
from nora.schemas import ScriptBeat, Shot, ShotPrompt, VideoBrief
from nora.services.renderer import OpenRouterRenderer, PlaceholderRenderer, get_renderer
from tests.fakes import FakeOpenRouterClient


def _brief() -> VideoBrief:
    return VideoBrief(
        product_name="Black Pepper",
        concept="bold",
        hook="Kandy heat",
        target_duration_s=30,
        script_beats=[ScriptBeat(t_start_s=0, t_end_s=3, voiceover="hi")],
        shots=[Shot(index=0, scene_description="x", duration_s=30)],
        shot_prompts=[ShotPrompt(index=0, t2v_prompt="x")],
        cta="Shop now",
        music_mood="warm",
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
    result = PlaceholderRenderer().render(_brief())
    assert result["status"] == "placeholder"
    assert result["mode"] == "none"
    assert result["shots"] == []


def test_openrouter_renderer_text_to_video_fallback(tmp_path):
    # No public media base URL → OpenRouter can't fetch a localhost first frame → text→video.
    settings = Settings(media_dir=tmp_path, media_public_base_url=None)
    client = FakeOpenRouterClient()
    result = OpenRouterRenderer(settings, client=client).render(_brief())

    assert result["status"] == "rendering"
    assert result["mode"] == "text_to_video"
    assert result["hero_image_url"].startswith("/media/")
    assert len(result["shots"]) == 1
    shot = result["shots"][0]
    assert shot["image_url"].startswith("/media/") and shot["video_job_id"]
    # text→video: no first frame was sent; and the image bytes were actually written under media_dir.
    assert client.video_calls[0]["first_frame_url"] is None
    assert list(tmp_path.rglob("*.png"))


def test_openrouter_renderer_image_to_video_when_public_base_set(tmp_path):
    # A public base URL → the still is passed as the first frame (image→video).
    settings = Settings(media_dir=tmp_path, media_public_base_url="https://pub.example")
    client = FakeOpenRouterClient()
    result = OpenRouterRenderer(settings, client=client).render(_brief())

    assert result["mode"] == "image_to_video"
    first_frame = client.video_calls[0]["first_frame_url"]
    assert first_frame and first_frame.startswith("https://pub.example/media/")


def test_openrouter_renderer_needs_a_key_or_client():
    # Hard-require, but lazy: construction is cheap (so building the marketing graph / running a
    # non-rendering turn needs no key); RENDERING without a key/client fails loudly.
    renderer = OpenRouterRenderer(Settings(openrouter_api_key=None))  # no raise at construction
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        renderer.render(_brief())
