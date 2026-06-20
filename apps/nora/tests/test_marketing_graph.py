"""Tests for the marketing workflow (M2).

Driven offline with a scripted structured model + the real (committed) SpiceDB for product
grounding. Covers: a valid VideoBrief that passes the eval guardrails, parallel ideation,
Send fan-out/fan-in (len(shot_prompts) == len(shots)), the bounded evaluator-optimizer loop,
and the placeholder render.
"""

from __future__ import annotations

import os

import pytest

from nora.config import get_settings
from nora.marketing.graph import build_marketing_graph, initial_marketing_state
from nora.marketing.nodes import _BriefCopy, _ScriptDraft, _Storyboard
from nora.schemas import ConceptIdea, Critique, ScriptBeat, Shot, VideoBrief
from tests.fakes import ScriptedStructuredModel

BANNED = ["cure", "guaranteed", "#1 in the world"]


def _good_script() -> _ScriptDraft:
    return _ScriptDraft(
        beats=[
            ScriptBeat(t_start_s=0, t_end_s=3, voiceover="Real Ceylon cinnamon, from Matale.", on_screen_text="From Matale"),
            ScriptBeat(t_start_s=3, t_end_s=15, voiceover="Hand-rolled quills, sweet and delicate."),
            ScriptBeat(t_start_s=15, t_end_s=27, voiceover="Grate it over your morning kiribath."),
            ScriptBeat(t_start_s=27, t_end_s=30, voiceover="Taste the origin. Shop Curry Nomad."),
        ]
    )


def _storyboard() -> _Storyboard:
    return _Storyboard(
        shots=[
            Shot(index=0, scene_description="Close-up of cinnamon quills", duration_s=10),
            Shot(index=1, scene_description="Hands grating cinnamon", duration_s=10),
            Shot(index=2, scene_description="Steaming plate of kiribath", duration_s=10),
        ]
    )


def _concepts() -> list[ConceptIdea]:
    return [
        ConceptIdea(angle=f"angle {i}", hook=f"Hook {i}: taste Matale", rationale="grounded")
        for i in range(3)
    ]


def _brief_copy() -> _BriefCopy:
    return _BriefCopy(cta="Shop now at currynomad.lk", music_mood="warm acoustic", hashtags=["#CurryNomad", "#CeylonCinnamon", "#Matale"])


def _passing_model() -> ScriptedStructuredModel:
    return ScriptedStructuredModel(
        {
            ConceptIdea: _concepts(),
            _ScriptDraft: [_good_script()],
            _Storyboard: [_storyboard()],
            Critique: [Critique(passed=True, issues=[], suggestions=[])],
            _BriefCopy: [_brief_copy()],
        }
    )


def _check_guardrails(brief: VideoBrief) -> None:
    assert 25 <= brief.target_duration_s <= 35
    assert 2 <= len(brief.shots) <= 8
    assert len(brief.shot_prompts) == len(brief.shots)
    assert brief.script_beats[0].t_start_s == 0
    assert brief.script_beats[0].voiceover
    assert brief.script_beats[0].t_end_s <= 3
    assert brief.cta
    text = " ".join(b.voiceover for b in brief.script_beats).lower()
    assert not any(b in text for b in BANNED)


def test_workflow_produces_valid_brief_passing_guardrails():
    graph = build_marketing_graph(model=_passing_model(), auto_approve=True)
    result = graph.invoke(
        initial_marketing_state("30s reel for authentic Matale origin", "Ceylon Cinnamon")
    )
    brief = result["brief"]
    assert isinstance(brief, VideoBrief)
    _check_guardrails(brief)


def test_product_grounding_uses_real_db_facts():
    graph = build_marketing_graph(model=_passing_model(), auto_approve=True)
    result = graph.invoke(initial_marketing_state("reel", "Ceylon Cinnamon (Alba)"))
    brief = result["brief"]
    # The product's real name + origin (Matale in the seed) must appear in the facts used.
    facts_text = " ".join(brief.product_facts_used)
    assert "Ceylon Cinnamon" in brief.product_name
    assert "Matale" in facts_text


def test_parallel_ideation_count():
    n = get_settings().marketing_num_concepts
    graph = build_marketing_graph(model=_passing_model(), auto_approve=True)
    result = graph.invoke(initial_marketing_state("reel", "Black Pepper"))
    assert len(result["concepts"]) == n


def test_send_fan_out_matches_shot_count():
    graph = build_marketing_graph(model=_passing_model(), auto_approve=True)
    result = graph.invoke(initial_marketing_state("reel", "Cloves"))
    assert len(result["shot_prompts"]) == len(result["shots"]) == 3


def test_evaluator_optimizer_loop_is_bounded():
    """A critic that never passes must stop at marketing_max_revisions, then assemble."""
    settings = get_settings()
    always_fail = ScriptedStructuredModel(
        {
            ConceptIdea: _concepts(),
            _ScriptDraft: [_good_script()],
            _Storyboard: [_storyboard()],
            Critique: [Critique(passed=False, issues=["too generic"], suggestions=["add origin"])],
            _BriefCopy: [_brief_copy()],
        }
    )
    graph = build_marketing_graph(model=always_fail, settings=settings, auto_approve=True)
    result = graph.invoke(initial_marketing_state("reel", "Turmeric"))
    assert result["revision_count"] == settings.marketing_max_revisions
    assert isinstance(result["brief"], VideoBrief)  # still assembles after the bound


def test_one_revision_then_pass():
    """Fail once, then pass: exactly one revision, then assemble."""
    model = ScriptedStructuredModel(
        {
            ConceptIdea: _concepts(),
            _ScriptDraft: [_good_script(), _good_script()],
            _Storyboard: [_storyboard()],
            Critique: [
                Critique(passed=False, issues=["weak hook"], suggestions=["sharpen hook"]),
                Critique(passed=True, issues=[], suggestions=[]),
            ],
            _BriefCopy: [_brief_copy()],
        }
    )
    result = build_marketing_graph(model=model, auto_approve=True).invoke(
        initial_marketing_state("reel", "Cardamom")
    )
    assert result["revision_count"] == 1
    _check_guardrails(result["brief"])


def test_render_returns_placeholder():
    graph = build_marketing_graph(model=_passing_model(), auto_approve=True)
    result = graph.invoke(initial_marketing_state("reel", "Cloves"))
    assert result["render_result"]["status"] == "placeholder"
    assert result["render_result"]["asset_ref"] is None


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="requires a live LLM key")
def test_live_workflow_builds_a_brief():
    graph = build_marketing_graph(auto_approve=True)
    result = graph.invoke(
        initial_marketing_state("30s reel highlighting authentic Matale origin", "Ceylon Cinnamon")
    )
    assert isinstance(result["brief"], VideoBrief)
