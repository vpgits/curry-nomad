"""Tests for the marketing workflow (M2).

Driven offline with a scripted structured model + the real (committed) SpiceDB for product
grounding. Covers: a valid PostBrief that passes the eval guardrails, parallel ideation,
Send fan-out/fan-in (len(shot_prompts) == len(shots)), the bounded evaluator-optimizer loop,
and the placeholder render.
"""

from __future__ import annotations

import os

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from nora.config import Settings, get_settings
from nora.marketing.graph import build_marketing_graph, initial_marketing_state
from nora.marketing.nodes import _BriefCopy, _PostCopy, _Storyboard
from nora.schemas import ConceptIdea, Critique, PostBrief, Shot
from nora.services.renderer import OpenRouterRenderer
from tests.fakes import FakeOpenRouterClient, ScriptedStructuredModel

BANNED = ["cure", "guaranteed", "#1 in the world"]


def _good_copy() -> _PostCopy:
    return _PostCopy(
        caption=(
            "Real Ceylon cinnamon, from Matale.\n"
            "Hand-rolled quills, sweet and delicate — grate it over your morning kiribath.\n"
            "Taste the origin. Shop Curry Nomad."
        ),
        on_screen_texts=["From Matale", "Hand-rolled quills", "Over kiribath", "Shop Curry Nomad"],
    )


def _storyboard() -> _Storyboard:
    return _Storyboard(
        shots=[
            Shot(index=0, scene_description="Close-up of cinnamon quills"),
            Shot(index=1, scene_description="Hands grating cinnamon"),
            Shot(index=2, scene_description="Steaming plate of kiribath"),
        ]
    )


def _concepts() -> list[ConceptIdea]:
    return [
        ConceptIdea(angle=f"angle {i}", hook=f"Hook {i}: taste Matale", rationale="grounded")
        for i in range(3)
    ]


def _brief_copy() -> _BriefCopy:
    return _BriefCopy(
        cta="Shop now at currynomad.lk", hashtags=["#CurryNomad", "#CeylonCinnamon", "#Matale"]
    )


def _passing_model() -> ScriptedStructuredModel:
    return ScriptedStructuredModel(
        {
            ConceptIdea: _concepts(),
            _PostCopy: [_good_copy()],
            _Storyboard: [_storyboard()],
            Critique: [Critique(passed=True, issues=[], suggestions=[])],
            _BriefCopy: [_brief_copy()],
        }
    )


def _check_guardrails(brief: dict | PostBrief) -> None:
    # State stores the brief as a dict; rehydrate so guardrails read it as the typed schema.
    brief = brief if isinstance(brief, PostBrief) else PostBrief(**brief)
    assert 2 <= len(brief.shots) <= 8
    assert len(brief.shot_prompts) == len(brief.shots)
    assert brief.caption.strip().splitlines()[0].strip()  # hook on the first caption line
    assert brief.cta
    text = (brief.caption + " " + " ".join(s.on_screen_text or "" for s in brief.shots)).lower()
    assert not any(b in text for b in BANNED)


def test_workflow_produces_valid_brief_passing_guardrails():
    graph = build_marketing_graph(model=_passing_model(), auto_approve=True)
    result = graph.invoke(
        initial_marketing_state("Instagram post for authentic Matale origin", "Ceylon Cinnamon")
    )
    brief = PostBrief(**result["brief"])  # state stores a dict; validates the round-trip
    _check_guardrails(brief)


def test_product_grounding_uses_real_db_facts():
    graph = build_marketing_graph(model=_passing_model(), auto_approve=True)
    result = graph.invoke(initial_marketing_state("Instagram post", "Ceylon Cinnamon (Alba)"))
    brief = PostBrief(**result["brief"])
    # The product's real name + origin (Matale in the seed) must appear in the facts used.
    facts_text = " ".join(brief.product_facts_used)
    assert "Ceylon Cinnamon" in brief.product_name
    assert "Matale" in facts_text


def test_parallel_ideation_count():
    n = get_settings().marketing_num_concepts
    graph = build_marketing_graph(model=_passing_model(), auto_approve=True)
    result = graph.invoke(initial_marketing_state("Instagram post", "Black Pepper"))
    assert len(result["concepts"]) == n


def test_send_fan_out_matches_shot_count():
    graph = build_marketing_graph(model=_passing_model(), auto_approve=True)
    result = graph.invoke(initial_marketing_state("Instagram post", "Cloves"))
    assert len(result["shot_prompts"]) == len(result["shots"]) == 3


def test_evaluator_optimizer_loop_is_bounded():
    """A critic that never passes must stop at marketing_max_revisions, then assemble."""
    settings = get_settings()
    always_fail = ScriptedStructuredModel(
        {
            ConceptIdea: _concepts(),
            _PostCopy: [_good_copy()],
            _Storyboard: [_storyboard()],
            Critique: [Critique(passed=False, issues=["too generic"], suggestions=["add origin"])],
            _BriefCopy: [_brief_copy()],
        }
    )
    graph = build_marketing_graph(model=always_fail, settings=settings, auto_approve=True)
    result = graph.invoke(initial_marketing_state("Instagram post", "Turmeric"))
    assert result["revision_count"] == settings.marketing_max_revisions
    assert PostBrief(**result["brief"]).shots  # still assembles after the bound


def test_one_revision_then_pass():
    """Fail once, then pass: exactly one revision, then assemble."""
    model = ScriptedStructuredModel(
        {
            ConceptIdea: _concepts(),
            _PostCopy: [_good_copy()],
            _Storyboard: [_storyboard()],
            Critique: [
                Critique(passed=False, issues=["weak hook"], suggestions=["sharpen hook"]),
                Critique(passed=True, issues=[], suggestions=[]),
            ],
            _BriefCopy: [_brief_copy()],
        }
    )
    result = build_marketing_graph(model=model, auto_approve=True).invoke(
        initial_marketing_state("Instagram post", "Cardamom")
    )
    assert result["revision_count"] == 1
    _check_guardrails(result["brief"])


def test_render_returns_placeholder():
    graph = build_marketing_graph(model=_passing_model(), auto_approve=True)
    result = graph.invoke(initial_marketing_state("Instagram post", "Cloves"))
    assert result["render_result"]["status"] == "placeholder"
    assert result["render_result"]["shots"] == []


def test_render_with_injected_openrouter_renderer(tmp_path):
    # The renderer is injectable: drive the real OpenRouter adapter through the graph offline.
    settings = Settings(media_dir=tmp_path)
    renderer = OpenRouterRenderer(settings, client=FakeOpenRouterClient())
    graph = build_marketing_graph(model=_passing_model(), auto_approve=True, renderer=renderer)
    result = graph.invoke(initial_marketing_state("Instagram post", "Cloves"))

    rr = result["render_result"]
    assert rr["status"] == "rendered"
    assert rr["hero_image_url"] and rr["shots"]
    assert all(s["image_url"] for s in rr["shots"])


def test_render_failure_degrades_to_error_result():
    # A render failure (network, or NORA_RENDERER=openrouter with no key) must not sink the turn —
    # the brief still ships and the render result records the error.
    class _BoomRenderer:
        def render_stills(self, brief):  # noqa: ARG002
            raise RuntimeError("openrouter down")

    graph = build_marketing_graph(model=_passing_model(), auto_approve=True, renderer=_BoomRenderer())
    result = graph.invoke(initial_marketing_state("Instagram post", "Cloves"))

    assert result["brief"]  # the finished brief survived the render failure
    assert result["render_result"]["status"] == "error"
    assert "openrouter down" in result["render_result"]["detail"]


def _stills_graph(tmp_path, client):
    """A graph wired to pause at the visual gate: real (fake-client) renderer, copy gate skipped,
    stills gate ON, with a checkpointer so the interrupt can pause + resume."""
    renderer = OpenRouterRenderer(Settings(media_dir=tmp_path), client=client)
    return build_marketing_graph(
        model=_passing_model(),
        auto_approve=True,  # skip the copy gate; isolate the stills gate
        auto_approve_stills=False,  # the gate under test
        renderer=renderer,
        checkpointer=InMemorySaver(),
    )


def test_still_review_pauses_before_finalize_then_approves(tmp_path):
    # The visual HITL gate pauses AFTER the stills are generated but BEFORE the post is finalized.
    client = FakeOpenRouterClient()
    graph = _stills_graph(tmp_path, client)
    cfg = {"configurable": {"thread_id": "t-still-approve"}}

    result = graph.invoke(initial_marketing_state("Instagram post", "Cloves"), cfg)
    payload = result["__interrupt__"][0].value
    assert payload["kind"] == "still_review"
    assert payload["shots"] and all(s.get("image_url") for s in payload["shots"])
    assert result["render_stills"]["status"] == "stills_ready"
    assert result.get("render_result") is None  # not finalized while paused for review

    result = graph.invoke(Command(resume={"approved": True}), cfg)
    rr = result["render_result"]
    assert rr["status"] == "rendered"
    assert rr["hero_image_url"] and all(s["image_url"] for s in rr["shots"])


def test_still_review_regenerate_then_approve(tmp_path):
    # Rejecting a still re-rolls just that shot, loops back to the gate, then approval finalizes.
    client = FakeOpenRouterClient()
    graph = _stills_graph(tmp_path, client)
    cfg = {"configurable": {"thread_id": "t-still-regen"}}

    graph.invoke(initial_marketing_state("Instagram post", "Cloves"), cfg)
    images_after_first = len(client.image_calls)

    # ask to re-roll shot 0 → a still is regenerated and we pause at the gate again
    result = graph.invoke(Command(resume={"regenerate": [0]}), cfg)
    assert len(client.image_calls) > images_after_first
    assert result["__interrupt__"][0].value["kind"] == "still_review"
    assert result["still_revision_count"] == 1

    # now approve → the post is finalized
    result = graph.invoke(Command(resume={"approved": True}), cfg)
    assert result["render_result"]["status"] == "rendered"


def test_still_review_skipped_for_placeholder(tmp_path):
    # The placeholder renderer has no stills to review, so the gate passes straight through even with
    # auto_approve_stills=False — no interrupt, no spend.
    graph = build_marketing_graph(
        model=_passing_model(),
        auto_approve=True,
        auto_approve_stills=False,
        checkpointer=InMemorySaver(),
    )
    cfg = {"configurable": {"thread_id": "t-still-placeholder"}}
    result = graph.invoke(initial_marketing_state("Instagram post", "Cloves"), cfg)
    assert "__interrupt__" not in result
    assert result["render_result"]["status"] == "placeholder"


def _sized_model(n: int = 6) -> ScriptedStructuredModel:
    """A model whose copy + storyboard have enough items that `num_images` (not the fixture) is the
    thing that bounds the post size."""
    return ScriptedStructuredModel(
        {
            ConceptIdea: _concepts(),
            _PostCopy: [
                _PostCopy(
                    caption="Real Ceylon cinnamon, from Matale.\nHand-rolled.\nShop Curry Nomad.",
                    on_screen_texts=[f"line {i}" for i in range(n)],
                )
            ],
            _Storyboard: [
                _Storyboard(shots=[Shot(index=i, scene_description=f"scene {i}") for i in range(n)])
            ],
            Critique: [Critique(passed=True, issues=[], suggestions=[])],
            _BriefCopy: [_brief_copy()],
        }
    )


def test_copy_gate_regenerate_changes_image_count_and_verbosity():
    # The operator re-tunes the post at the copy gate: regenerate re-runs write_copy with the new
    # image count + verbosity and re-pauses; approve then honors the count downstream.
    graph = build_marketing_graph(
        model=_sized_model(6),
        auto_approve=False,  # copy gate ON — under test
        auto_approve_stills=True,  # skip the later visual gate
        checkpointer=InMemorySaver(),
    )
    cfg = {"configurable": {"thread_id": "t-copy-regen"}}

    result = graph.invoke(initial_marketing_state("Instagram post", "Cloves"), cfg)
    payload = result["__interrupt__"][0].value
    assert payload["kind"] == "copy_review"
    assert payload["num_images"] == 4  # settings default seeds the control
    assert payload["verbosity"] == "standard"
    assert len(payload["on_screen_texts"]) == 4  # capped to num_images

    # re-tune to 6 images + detailed → regenerate → re-pause at the copy gate
    result = graph.invoke(
        Command(resume={"regenerate": True, "num_images": 6, "verbosity": "detailed"}), cfg
    )
    payload = result["__interrupt__"][0].value
    assert payload["kind"] == "copy_review"
    assert payload["num_images"] == 6
    assert payload["verbosity"] == "detailed"
    assert len(payload["on_screen_texts"]) == 6

    # approve → storyboard + shots honor the chosen count
    result = graph.invoke(Command(resume={"approved": True}), cfg)
    brief = PostBrief(**result["brief"])
    assert len(brief.shots) == 6
    assert len(brief.shot_prompts) == 6


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="requires a live LLM key")
def test_live_workflow_builds_a_brief():
    graph = build_marketing_graph(auto_approve=True)
    result = graph.invoke(
        initial_marketing_state("Instagram post highlighting authentic Matale origin", "Ceylon Cinnamon")
    )
    assert PostBrief(**result["brief"]).product_name
