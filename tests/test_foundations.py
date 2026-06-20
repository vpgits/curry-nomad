"""Foundation tests: config, observability, renderer adapters (M6 coverage top-up)."""

from __future__ import annotations

import json

import pytest

from nora.config import get_settings
from nora.observability import get_logger, setup_logging
from nora.schemas import ScriptBeat, Shot, ShotPrompt, VideoBrief
from nora.services.renderer import OpenRouterRenderer, PlaceholderRenderer, get_renderer


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
    assert s.renderer == "placeholder"
    assert s.db_path.name == "curry_nomad.db"
    assert s.embedding_dims == 1536


def test_logging_emits_structured_json(capsys):
    setup_logging(json_logs=True)
    get_logger("test").info("hello_event", widget="spice")
    line = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "hello_event"
    assert record["widget"] == "spice"
    assert record["level"] == "info"


def test_default_renderer_is_placeholder():
    assert isinstance(get_renderer(get_settings()), PlaceholderRenderer)


def test_placeholder_render_makes_no_external_call():
    result = PlaceholderRenderer().render(_brief())
    assert result["status"] == "placeholder"
    assert result["asset_ref"] is None


def test_openrouter_renderer_is_a_documented_stub():
    renderer = OpenRouterRenderer(get_settings())
    with pytest.raises(NotImplementedError):
        renderer.render(_brief())
