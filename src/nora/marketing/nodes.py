"""Marketing workflow nodes.

Each node is built by a small factory (`make_*`) that captures its dependencies (model,
settings, db) and returns the actual node function with the signature LangGraph expects. This
keeps the node logic here, lets the graph wire concrete deps in `graph.py`, and makes every
node unit-testable with an injected fake model.

Two internal wrapper schemas (`_ScriptDraft`, `_Storyboard`) exist only because
`with_structured_output` needs a single model class to return a *list* of items; `_BriefCopy`
carries the finishing copy. They're implementation details, not part of the public contract.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from langgraph.runtime import Runtime
from pydantic import BaseModel

from nora.config import Settings
from nora.marketing import prompts
from nora.observability import get_logger
from nora.schemas import (
    ConceptIdea,
    Critique,
    ScriptBeat,
    Shot,
    ShotPrompt,
    VideoBrief,
)
from nora.services.renderer import get_renderer

log = get_logger(__name__)


# --- internal structured-output wrappers ----------------------------------------------


class _ScriptDraft(BaseModel):
    beats: list[ScriptBeat]


class _Storyboard(BaseModel):
    shots: list[Shot]


class _BriefCopy(BaseModel):
    cta: str
    music_mood: str
    hashtags: list[str]


# --- grounding: pull the product's real row -------------------------------------------


def lookup_product_facts(spice_db, product_hint: str | None) -> dict:
    """Find the chosen product's real row (name, origin, grams, price, category) via the
    read-only SpiceDB. Falls back to the first product if the hint matches nothing."""
    cols = "product_id, name, category, origin, grams, unit_price_lkr"
    hint = (product_hint or "").replace("'", "''")  # escape quotes; run_sql is SELECT-only
    query = (
        f"SELECT {cols} FROM products "
        f"WHERE name LIKE '%{hint}%' OR sku LIKE '%{hint}%' ORDER BY product_id LIMIT 1"
        if hint
        else f"SELECT {cols} FROM products ORDER BY product_id LIMIT 1"
    )
    result = spice_db.run_sql(query)
    if not result["rows"]:
        result = spice_db.run_sql(f"SELECT {cols} FROM products ORDER BY product_id LIMIT 1")
    return dict(zip(result["columns"], result["rows"][0], strict=True))


# --- nodes ----------------------------------------------------------------------------


def make_fetch_product(settings: Settings, spice_db):
    """Fetch the chosen product's real row once, up front, and thread it through state so every
    downstream node (and each Send worker) is grounded in the same facts."""

    def fetch_product(state) -> dict:
        facts = lookup_product_facts(spice_db, state.get("product_hint"))
        log.info("marketing.product", name=facts.get("name"), origin=facts.get("origin"))
        return {"product_facts": facts}

    return fetch_product


def make_load_brand(settings: Settings):
    """Read brand voice from the long-term Store (semantic search) when wired; else fall back.

    Memory access is via `runtime.store` (per the docs), not a bare param — so this is the
    same node in M2 (no store → fallback) and M3 (store seeded → real brand voice).
    """

    def load_brand(state, runtime: Runtime) -> dict:
        voice = prompts.DEFAULT_BRAND_VOICE
        store = getattr(runtime, "store", None)
        if store is not None:
            from nora.memory import BRAND

            items = store.search(BRAND, query="brand voice, tone and style", limit=3)
            if items:
                voice = "\n".join(i.value["text"] for i in items)
        return {"brand_voice": voice}

    return load_brand


def make_ideate(model, settings: Settings):
    """Generate `marketing_num_concepts` concepts IN PARALLEL (parallelization within a node).

    The calls are I/O-bound model invocations, so a thread pool gives real concurrency.
    `executor.map` preserves input order, so concept[i] always corresponds to angle seed i.
    """

    def ideate(state) -> dict:
        facts = state["product_facts"]
        brand, request = state["brand_voice"], state["request"]
        n = settings.marketing_num_concepts

        def one(i: int) -> ConceptIdea:
            structured = model.with_structured_output(ConceptIdea)
            return structured.invoke(prompts.ideate_prompt(brand, facts, request, i))

        with ThreadPoolExecutor(max_workers=n) as executor:
            concepts = list(executor.map(one, range(n)))
        log.info("marketing.ideate", concepts=len(concepts))
        return {"concepts": concepts}

    return ideate


def make_choose_concept(settings: Settings):
    """Pick the lead concept. We take the first (angle seed 0); a structured judge could rank
    them instead — but the brand-voice judging happens later in `critique`."""

    def choose_concept(state) -> dict:
        return {"chosen_concept": state["concepts"][0]}

    return choose_concept


def make_write_script(model, settings: Settings):
    def write_script(state) -> dict:
        facts = state["product_facts"]
        concept = state["chosen_concept"]
        prompt = prompts.script_prompt(concept, state["brand_voice"], facts, target_s=30)
        draft = model.with_structured_output(_ScriptDraft).invoke(prompt)
        return {"script_beats": draft.beats}

    return write_script


def make_storyboard(model, settings: Settings):
    def storyboard(state) -> dict:
        facts = state["product_facts"]
        prompt = prompts.storyboard_prompt(state["script_beats"], facts)
        board = model.with_structured_output(_Storyboard).invoke(prompt)
        # Reset shot_prompts (None) so a revision loop doesn't accumulate stale prompts.
        return {"shots": board.shots, "shot_prompts": None}

    return storyboard


def make_shot_prompt_worker(model, settings: Settings):
    """One Send worker per shot (map-reduce parallel). Builds the ShotPrompt in code with the
    shot's real index, so len(shot_prompts) == len(shots) by construction."""

    def shot_prompt_worker(payload) -> dict:
        shot: Shot = payload["shot"]
        facts = payload["product_facts"]
        text = model.invoke(prompts.shot_prompt_prompt(shot, payload["brand_voice"], facts))
        content = text.content if hasattr(text, "content") else str(text)
        return {"shot_prompts": [ShotPrompt(index=shot.index, t2v_prompt=content)]}

    return shot_prompt_worker


def make_critique(model, settings: Settings):
    """Evaluator: score the draft against brand voice + platform rules."""

    def critique(state) -> dict:
        prompt = prompts.critique_prompt(
            state["script_beats"], state["shot_prompts"], state["brand_voice"]
        )
        verdict = model.with_structured_output(Critique).invoke(prompt)
        log.info(
            "marketing.revision",
            iteration=state["revision_count"],
            verdict="pass" if verdict.passed else "fail",
        )
        return {"critique": verdict}

    return critique


def make_route_after_critique(settings: Settings):
    """Optimizer gate: assemble if it passed or we've hit the revision bound; else revise."""

    def route_after_critique(state) -> str:
        verdict: Critique = state["critique"]
        if verdict.passed or state["revision_count"] >= settings.marketing_max_revisions:
            return "assemble"
        return "revise"

    return route_after_critique


def make_revise(model, settings: Settings):
    def revise(state) -> dict:
        verdict: Critique = state["critique"]
        prompt = prompts.revise_prompt(
            state["script_beats"], verdict.issues, verdict.suggestions
        )
        draft = model.with_structured_output(_ScriptDraft).invoke(prompt)
        return {"script_beats": draft.beats, "revision_count": state["revision_count"] + 1}

    return revise


def make_assemble(model, settings: Settings):
    """Compose the final VideoBrief: structural fields come from state (so guardrails hold by
    construction); the model fills only the finishing copy (cta, music mood, hashtags)."""

    def assemble(state) -> dict:
        facts = state["product_facts"]
        concept = state["chosen_concept"]
        beats: list[ScriptBeat] = state["script_beats"]
        shots: list[Shot] = state["shots"]
        shot_prompts = sorted(state["shot_prompts"], key=lambda p: p.index)

        copy = model.with_structured_output(_BriefCopy).invoke(
            prompts.brief_copy_prompt(concept, state["brand_voice"], facts)
        )
        brief = VideoBrief(
            product_name=facts["name"],
            concept=concept.angle,
            hook=concept.hook,
            target_duration_s=max((b.t_end_s for b in beats), default=30.0),
            script_beats=beats,
            shots=shots,
            shot_prompts=shot_prompts,
            cta=copy.cta,
            music_mood=copy.music_mood,
            hashtags=copy.hashtags,
            product_facts_used=[
                facts["name"],
                f"origin: {facts['origin']}",
                f"{facts['grams']}g pack",
                f"LKR {facts['unit_price_lkr']}",
                str(facts["category"]),
            ],
        )
        return {"brief": brief}

    return assemble


def make_render(settings: Settings):
    """Render the brief. Placeholder by default (no external call, no spend)."""

    def render(state) -> dict:
        result = get_renderer(settings).render(state["brief"])
        return {"render_result": result}

    return render
