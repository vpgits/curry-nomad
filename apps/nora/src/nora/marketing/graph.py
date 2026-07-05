"""The marketing workflow subgraph (the WORKFLOW).

    START → fetch_product → load_brand → ideate(∥) → choose_concept → write_copy
          → storyboard → [Send fan-out] shot_prompt_worker(∥) → critique
          critique ──pass OR revisions≥max──→ assemble → render_stills → still_review
                   └──fail & < max──→ revise → storyboard      (evaluator-optimizer loop)
          still_review ──approved──→ finalize_post → END
                       └──regenerate──→ regenerate_stills → still_review   (visual review loop)

This is the contrast to the analytics agent: the shape is fixed and known, so it's a
deterministic pipeline — chaining, parallelization (ideation + per-shot image prompts), and a
bounded evaluator-optimizer loop. There are two human gates: the copy `human_review` (between
write_copy and storyboard) and the visual `still_review` (approve the generated stills before
the Instagram post is finalized).
"""

from __future__ import annotations

from langchain.chat_models import init_chat_model
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, Send

from nora.config import Settings, get_settings
from nora.marketing import nodes
from nora.schemas import Context
from nora.services.spice_db import build_spice_db
from nora.state import MarketingState


def fan_out_shots(state: MarketingState) -> list[Send]:
    """Map-reduce fan-out: one shot_prompt_worker per shot, carrying the grounding facts."""
    return [
        Send(
            "shot_prompt_worker",
            {
                "shot": shot,
                "product_facts": state["product_facts"],
                "brand_voice": state["brand_voice"],
            },
        )
        for shot in state["shots"]
    ]


def build_marketing_graph(
    *,
    settings: Settings | None = None,
    model=None,
    spice_db=None,
    checkpointer=None,
    store=None,
    auto_approve: bool = False,
    auto_choose: bool = True,
    auto_approve_stills: bool = True,
    renderer=None,
):
    """Compile the marketing workflow. `model`/`spice_db` are injectable for offline tests.

    `auto_approve=True` makes the human_review gate pass through without interrupting (eval
    mode). With the default (False), running the graph requires a checkpointer + thread_id so
    the interrupt can pause and resume.

    `auto_choose` controls the concept gate and defaults to True (auto-pick the first concept) so
    every unattended caller — evals and the offline tests — keeps its single, copy-review
    interrupt. The orchestrator passes `auto_choose=False` to add the interactive concept-pick
    gate before the copy gate.

    `auto_approve_stills` controls the visual gate and likewise defaults to True (skip) so
    unattended callers don't stall on it; the orchestrator passes `auto_approve_stills=False` (when
    the openrouter renderer is active and `stills_review_enabled`) to let the operator approve or
    re-roll the generated stills before the Instagram post is finalized.
    """
    settings = settings or get_settings()
    if model is None:
        # Creative steps want some variation; the critic/assembler tolerate it fine.
        # disable_streaming: every marketing node is a with_structured_output call (plus the plain
        # shot-prompt text), all consumed into typed state — the user-facing output is the
        # orchestrator's hand-built summary message, not an LLM token stream. With streaming on,
        # Aegra's `messages` stream would surface those internal calls' deltas as phantom partial
        # messages in the useStream UI, so the marketing path stays off the token stream too. No
        # UX cost — nothing here is streamed to the user. See orchestrator.py for the full rationale.
        model = init_chat_model(
            settings.model_for("marketing"), temperature=0.7, disable_streaming=True
        )
    if spice_db is None:
        spice_db = build_spice_db(settings)

    builder = StateGraph(MarketingState, context_schema=Context)
    builder.add_node("fetch_product", nodes.make_fetch_product(settings, spice_db))
    builder.add_node("load_brand", nodes.make_load_brand(settings))
    # ideate fans out N model calls via .batch inside one node; a RetryPolicy retries a single flaky
    # call instead of failing the whole superstep (batch re-raises the first worker error otherwise).
    builder.add_node("ideate", nodes.make_ideate(model, settings), retry_policy=RetryPolicy(max_attempts=3))
    builder.add_node("choose_concept", nodes.make_choose_concept(settings, auto_choose=auto_choose))
    builder.add_node("write_copy", nodes.make_write_copy(model, settings))
    builder.add_node("human_review", nodes.make_human_review(settings, auto_approve=auto_approve))
    builder.add_node("cancel", nodes.make_cancel(settings))
    builder.add_node("storyboard", nodes.make_storyboard(model, settings))
    builder.add_node("shot_prompt_worker", nodes.make_shot_prompt_worker(model, settings))
    builder.add_node("critique", nodes.make_critique(model, settings))
    builder.add_node("revise", nodes.make_revise(model, settings))
    builder.add_node("assemble", nodes.make_assemble(model, settings))
    # Staged render + the visual HITL gate: stills → review → (regenerate loop | finalize post).
    builder.add_node("render_stills", nodes.make_render_stills(settings, renderer=renderer))
    builder.add_node(
        "still_review", nodes.make_still_review(settings, auto_approve_stills=auto_approve_stills)
    )
    builder.add_node("regenerate_stills", nodes.make_regenerate_stills(settings, renderer=renderer))
    builder.add_node("finalize_post", nodes.make_finalize_post(settings))

    builder.add_edge(START, "fetch_product")
    builder.add_edge("fetch_product", "load_brand")
    builder.add_edge("load_brand", "ideate")
    builder.add_edge("ideate", "choose_concept")
    builder.add_edge("choose_concept", "write_copy")
    builder.add_edge("write_copy", "human_review")  # HITL gate before expensive steps
    # human_review returns Command(goto="write_copy" | "storyboard" | "cancel") — edges inferred from
    # its Command[Literal[...]] return annotation. "write_copy" is the copy-regenerate loop (operator
    # re-tunes image count / verbosity at the gate); it's cheap since images render after approval.
    builder.add_conditional_edges("storyboard", fan_out_shots, ["shot_prompt_worker"])
    builder.add_edge("shot_prompt_worker", "critique")  # fan-in
    builder.add_conditional_edges(
        "critique", nodes.make_route_after_critique(settings), ["assemble", "revise"]
    )
    builder.add_edge("revise", "storyboard")  # evaluator-optimizer loop
    builder.add_edge("assemble", "render_stills")
    builder.add_edge("render_stills", "still_review")
    # still_review returns Command(goto="regenerate_stills" | "finalize_post") — edges inferred from
    # its Command[Literal[...]] return annotation.
    builder.add_edge("regenerate_stills", "still_review")  # visual review loop
    builder.add_edge("finalize_post", END)
    builder.add_edge("cancel", END)

    return builder.compile(checkpointer=checkpointer, store=store)


def initial_marketing_state(request: str, product_hint: str | None = None) -> dict:
    """Seed values for a marketing run (reducer channels must start as empty lists)."""
    return {
        "request": request,
        "product_hint": product_hint,
        "concepts": [],
        "shot_prompts": [],
        "revision_count": 0,
    }
