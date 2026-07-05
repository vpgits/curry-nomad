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

import json
from typing import Literal

from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from pydantic import BaseModel

from nora.config import Settings
from nora.marketing import prompts
from nora.observability import get_logger
from nora.schemas import (
    ConceptIdea,
    Critique,
    PostBrief,
    Shot,
    ShotPrompt,
)
from nora.services.renderer import get_renderer

log = get_logger(__name__)


# --- internal structured-output wrappers ----------------------------------------------


class _PostCopy(BaseModel):
    caption: str  # the Instagram caption body
    on_screen_texts: list[str]  # one short overlay line per intended image


class _Storyboard(BaseModel):
    shots: list[Shot]


class _BriefCopy(BaseModel):
    cta: str
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
            from nora.memory import GLOBAL_BRAND

            items = store.search(GLOBAL_BRAND, query="brand voice, tone and style", limit=3)
            if items:
                voice = "\n".join(i.value["text"] for i in items)
        return {"brand_voice": voice}

    return load_brand


def make_ideate(model, settings: Settings):
    """Generate `marketing_num_concepts` concepts IN PARALLEL (parallelization within a node).

    Uses `with_structured_output(...).batch(prompts, config=config)` rather than a hand-rolled
    ThreadPoolExecutor: `.batch` runs the I/O-bound calls concurrently in LangChain's own executor,
    preserves input order (concept[i] ← angle seed i), and — crucially — PROPAGATES the run `config`
    (callbacks/run-tree) into the child calls, so each concept generation nests under this run in the
    trace instead of escaping as a detached session-less trace (the raw thread pool dropped the
    context, since OpenTelemetry's span context is thread-local). The `ideate` graph node also carries
    a RetryPolicy (see graph.py), so a single flaky call is retried instead of failing the superstep.
    """

    def ideate(state, config) -> dict:
        facts = state["product_facts"]
        brand, request = state["brand_voice"], state["request"]
        n = settings.marketing_num_concepts
        structured = model.with_structured_output(ConceptIdea)
        seed_prompts = [prompts.ideate_prompt(brand, facts, request, i) for i in range(n)]
        concepts = structured.batch(seed_prompts, config=config)
        log.info("marketing.ideate", concepts=len(concepts))
        return {"concepts": [c.model_dump() for c in concepts]}

    return ideate


def make_choose_concept(settings: Settings, *, auto_choose: bool = True):
    """Pick the lead concept from the parallel ideation.

    `auto_choose=True` (the default — and what every unattended run uses: evals, the offline
    tests) takes the first concept (angle seed 0), preserving the original behaviour. The
    orchestrator opts into `auto_choose=False` to turn this into a *second* HITL gate: an
    `interrupt()` that hands the N concepts to the operator and resumes with the one they pick —
    the interactive-selection generative-UI pattern (the parallel fan-out finally becomes a real
    choice). The payload carries `kind: "concept_pick"` so the UI can tell it apart from the
    later script-review interrupt.
    """

    def choose_concept(state) -> dict:
        concepts = state["concepts"]
        if auto_choose or len(concepts) <= 1:
            return {"chosen_concept": concepts[0]}

        log.info("hitl.raised", question="choose concept")
        decision = interrupt(
            {
                "kind": "concept_pick",
                "question": "Which creative concept should we develop?",
                "concepts": concepts,  # list of ConceptIdea dicts (JSON-native state)
            }
        )
        # Resume normalization (mirrors human_review): useStream resumes with a structured
        # Command(resume={"chosen_index": n}) → dict; a JSON string is parsed; a bare int works too.
        if isinstance(decision, str):
            try:
                decision = json.loads(decision)
            except (ValueError, TypeError):
                pass
        if isinstance(decision, dict):
            idx = decision.get("chosen_index", 0)
        elif isinstance(decision, int):
            idx = decision
        else:
            idx = 0
        if not isinstance(idx, int) or not (0 <= idx < len(concepts)):
            idx = 0
        log.info("marketing.concept_chosen", index=idx)
        return {"chosen_concept": concepts[idx]}

    return choose_concept


def _post_size(state, settings: Settings) -> tuple[int, str]:
    """The operator-controlled post size + caption verbosity (seeded from settings when unset)."""
    num_images = state.get("num_images") or settings.marketing_num_images
    verbosity = state.get("verbosity") or settings.marketing_verbosity
    return num_images, verbosity


def make_write_copy(model, settings: Settings):
    def write_copy(state) -> dict:
        facts = state["product_facts"]
        concept = ConceptIdea(**state["chosen_concept"])
        num_images, verbosity = _post_size(state, settings)
        prompt = prompts.copy_prompt(
            concept, state["brand_voice"], facts, verbosity=verbosity, num_images=num_images
        )
        draft = model.with_structured_output(_PostCopy).invoke(prompt)
        # `num_images` is authoritative — cap the copy lines so the count is always what the operator chose.
        lines = draft.on_screen_texts[:num_images]
        return {"post_copy": {"caption": draft.caption, "on_screen_texts": lines}}

    return write_copy


def make_human_review(settings: Settings, *, auto_approve: bool = False):
    """The single copy HITL gate (M3). It sits BEFORE the expensive creative steps (storyboard +
    per-shot image prompts), so the operator approves/edits/rejects the post copy before compute is
    spent — gate by risk, not a final "are you sure?".

    `interrupt()` is called exactly once. The node re-runs from the top on resume, so the
    branch (approve / edit / reject) is decided from the resumed decision. `auto_approve=True`
    skips the pause entirely — used by the eval harness to run unattended.
    """

    def human_review(state) -> Command[Literal["write_copy", "storyboard", "cancel"]]:
        if auto_approve:
            return Command(goto="storyboard", update={"approved": True})

        post_copy = state["post_copy"]  # {"caption", "on_screen_texts"} — JSON-native state
        num_images, verbosity = _post_size(state, settings)
        log.info("hitl.raised", question="approve copy")
        decision = interrupt(
            {
                "kind": "copy_review",  # lets the UI distinguish this from the concept_pick gate
                "question": "Approve the post copy before we generate the images?",
                "caption": post_copy["caption"],
                "on_screen_texts": post_copy["on_screen_texts"],
                # Seed the copy-gate controls so the operator can re-tune size/verbosity + regenerate.
                "num_images": num_images,
                "verbosity": verbosity,
            }
        )
        # Resume transport-normalization. useStream resumes with a structured
        # Command(resume={"approved": ..., "edited_copy": ...}) → `decision` is a dict. Some clients
        # resolve an interrupt with a JSON *string* instead, so parse it back to a dict here —
        # otherwise `bool("{...}")` is truthy for *any* non-empty string and reject/edits break.
        if isinstance(decision, str):
            try:
                decision = json.loads(decision)
            except (ValueError, TypeError):
                pass

        # Regenerate: re-run write_copy with the operator's image-count + verbosity, then pause here
        # again. Cheap — the images aren't rendered until after approval.
        if isinstance(decision, dict) and decision.get("regenerate"):
            n = decision.get("num_images", num_images)
            n = n if isinstance(n, int) and 1 <= n <= 8 else num_images
            v = decision.get("verbosity", verbosity)
            v = v if v in ("concise", "standard", "detailed") else verbosity
            return Command(goto="write_copy", update={"num_images": n, "verbosity": v})

        approved = decision.get("approved", False) if isinstance(decision, dict) else bool(decision)
        if not approved:
            return Command(goto="cancel", update={"approved": False})

        update: dict = {"approved": True}
        edited = decision.get("edited_copy") if isinstance(decision, dict) else None
        if edited:  # honor edited copy — validate the shape, then store as a dict
            validated = _PostCopy(**edited)
            update["post_copy"] = {
                "caption": validated.caption,
                "on_screen_texts": validated.on_screen_texts,
            }
        return Command(goto="storyboard", update=update)

    return human_review


def make_cancel(settings: Settings):
    """Terminal node when the operator rejects the post copy."""

    def cancel(state) -> dict:
        log.info("marketing.cancelled")
        return {
            "render_result": {
                "status": "cancelled",
                "shots": [],
                "detail": "creative cancelled by user",
            }
        }

    return cancel


def make_storyboard(model, settings: Settings):
    def storyboard(state) -> dict:
        facts = state["product_facts"]
        post_copy = state["post_copy"]
        on_screen = post_copy.get("on_screen_texts") or []
        prompt = prompts.storyboard_prompt(post_copy["caption"], on_screen, facts)
        board = model.with_structured_output(_Storyboard).invoke(prompt)
        num_images, _ = _post_size(state, settings)
        # Pin each image's on-screen line by index (the approved copy is authoritative), falling back
        # to whatever the model chose. Cap to the operator's `num_images` so the post size is exact.
        # Reset shot_prompts (None) so a revision doesn't accumulate stale ones.
        shots = []
        for i, s in enumerate(board.shots[:num_images]):
            d = s.model_dump()
            if i < len(on_screen):
                d["on_screen_text"] = on_screen[i]
            shots.append(d)
        return {"shots": shots, "shot_prompts": None}

    return storyboard


def make_shot_prompt_worker(model, settings: Settings):
    """One Send worker per shot (map-reduce parallel). Builds the ShotPrompt in code with the
    shot's real index, so len(shot_prompts) == len(shots) by construction."""

    def shot_prompt_worker(payload) -> dict:
        shot = Shot(**payload["shot"])  # the Send carries a dict (JSON-native state)
        facts = payload["product_facts"]
        text = model.invoke(prompts.shot_prompt_prompt(shot, payload["brand_voice"], facts))
        content = text.content if hasattr(text, "content") else str(text)
        return {"shot_prompts": [ShotPrompt(index=shot.index, image_prompt=content).model_dump()]}

    return shot_prompt_worker


def make_critique(model, settings: Settings):
    """Evaluator: score the draft against brand voice + platform rules."""

    def critique(state) -> dict:
        caption = state["post_copy"]["caption"]
        shot_prompts = [ShotPrompt(**p) for p in state["shot_prompts"]]
        prompt = prompts.critique_prompt(caption, shot_prompts, state["brand_voice"])
        verdict = model.with_structured_output(Critique).invoke(prompt)
        log.info(
            "marketing.revision",
            iteration=state.get("revision_count", 0),
            verdict="pass" if verdict.passed else "fail",
        )
        return {"critique": verdict.model_dump()}

    return critique


def make_route_after_critique(settings: Settings):
    """Optimizer gate: assemble if it passed or we've hit the revision bound; else revise."""

    def route_after_critique(state) -> str:
        verdict = state["critique"]  # Critique dict
        # On the final allowed pass the bound is hit AFTER critique has run, so that last verdict is
        # informational only (logged, then we assemble regardless). Bounded either way: revision_count
        # only ever increments in `revise`, so the loop always terminates.
        if verdict["passed"] or state.get("revision_count", 0) >= settings.marketing_max_revisions:
            return "assemble"
        return "revise"

    return route_after_critique


def make_revise(model, settings: Settings):
    def revise(state) -> dict:
        verdict = state["critique"]  # Critique dict
        caption = state["post_copy"]["caption"]
        num_images, verbosity = _post_size(state, settings)
        prompt = prompts.revise_prompt(
            caption, verdict["issues"], verdict["suggestions"],
            verbosity=verbosity, num_images=num_images,
        )
        draft = model.with_structured_output(_PostCopy).invoke(prompt)
        return {
            "post_copy": {
                "caption": draft.caption,
                "on_screen_texts": draft.on_screen_texts[:num_images],
            },
            "revision_count": state.get("revision_count", 0) + 1,
        }

    return revise


def make_assemble(model, settings: Settings):
    """Compose the final PostBrief: structural fields come from state (so guardrails hold by
    construction); the model fills only the finishing copy (cta, hashtags)."""

    def assemble(state) -> dict:
        facts = state["product_facts"]
        # Rehydrate the JSON-native state fields into typed models for construction.
        concept = ConceptIdea(**state["chosen_concept"])
        shots = [Shot(**s) for s in state["shots"]]
        shot_prompts = sorted((ShotPrompt(**p) for p in state["shot_prompts"]), key=lambda p: p.index)

        copy = model.with_structured_output(_BriefCopy).invoke(
            prompts.brief_copy_prompt(concept, state["brand_voice"], facts)
        )
        brief = PostBrief(
            product_name=facts["name"],
            concept=concept.angle,
            hook=concept.hook,
            caption=state["post_copy"]["caption"],
            shots=shots,
            shot_prompts=shot_prompts,
            cta=copy.cta,
            hashtags=copy.hashtags,
            product_facts_used=[
                facts["name"],
                f"origin: {facts['origin']}",
                f"{facts['grams']}g pack",
                f"LKR {facts['unit_price_lkr']}",
                str(facts["category"]),
            ],
        )
        return {"brief": brief.model_dump()}

    return assemble


def make_render_stills(settings: Settings, *, renderer=None):
    """Staged render, step 1: generate the hero + per-shot stills, so the operator can review them
    at the still-review gate before we finalize the Instagram post. Best-effort: a stills failure
    degrades to an error result rather than crashing the turn."""

    def render_stills(state) -> dict:
        try:
            r = renderer or get_renderer(settings)
            result = r.render_stills(PostBrief(**state["brief"]))
        except Exception as exc:  # noqa: BLE001 — never let rendering sink the finished brief
            log.info("render.stills.error", error=str(exc))
            result = {"status": "error", "shots": [], "detail": f"stills failed: {exc}"}
        return {"render_stills": result}

    return render_stills


def make_still_review(settings: Settings, *, auto_approve_stills: bool = True):
    """HITL gate on the generated stills — the visual analogue of the copy `human_review`. It sits
    BEFORE the post is finalized, so the operator approves the images (or asks to re-roll specific
    shots). `interrupt()` fires at most once per pass; the node re-runs on resume and routes from
    the resumed decision.

    Skips the pause (→ finalize_post) when `auto_approve_stills` is set (evals/tests), when there are
    no reviewable stills (the placeholder renderer, or a stills error), or once the regenerate loop
    reaches `stills_max_revisions`."""

    def still_review(state) -> Command[Literal["regenerate_stills", "finalize_post"]]:
        stills = state.get("render_stills") or {}
        shots = stills.get("shots") or []
        reviewable = any(s.get("image_url") for s in shots)
        if (
            auto_approve_stills
            or not reviewable
            or state.get("still_revision_count", 0) >= settings.stills_max_revisions
        ):
            return Command(goto="finalize_post")

        log.info("hitl.raised", question="approve stills")
        decision = interrupt(
            {
                "kind": "still_review",  # lets the UI distinguish this from the concept/copy gates
                "question": "Approve these images for your Instagram post?",
                "hero_image_url": stills.get("hero_image_url"),
                "shots": [
                    {
                        "index": s["index"],
                        "image_url": s.get("image_url"),
                        "scene_description": s.get("scene_description"),
                    }
                    for s in shots
                ],
            }
        )
        # Same resume transport-normalization as human_review: a structured dict, or a JSON string
        # some clients send when resolving an interrupt.
        if isinstance(decision, str):
            try:
                decision = json.loads(decision)
            except (ValueError, TypeError):
                pass

        regen = decision.get("regenerate") if isinstance(decision, dict) else None
        if regen:  # re-roll the flagged shots (index -1 = the hero), then loop back to review
            overrides = decision.get("prompt_overrides") if isinstance(decision, dict) else None
            return Command(
                goto="regenerate_stills",
                update={"still_regen": {"indices": list(regen), "overrides": overrides or {}}},
            )
        return Command(goto="finalize_post")  # approved

    return still_review


def make_regenerate_stills(settings: Settings, *, renderer=None):
    """Re-roll the stills the operator rejected (carried in `still_regen`), then loop back to the
    still-review gate. Bounded: `still_revision_count` is incremented here and checked in the gate."""

    def regenerate_stills(state) -> dict:
        regen = state.get("still_regen") or {}
        stills = state.get("render_stills") or {}
        try:
            r = renderer or get_renderer(settings)
            stills = r.regenerate_stills(
                PostBrief(**state["brief"]),
                stills,
                list(regen.get("indices") or []),
                regen.get("overrides") or {},
            )
        except Exception as exc:  # noqa: BLE001 — a failed re-roll keeps the prior stills
            log.info("render.stills.regenerate.error", error=str(exc))
        return {
            "render_stills": stills,
            "still_revision_count": state.get("still_revision_count", 0) + 1,
        }

    return regenerate_stills


def make_finalize_post(settings: Settings):
    """Staged render, final step: promote the reviewed stills to the finished Instagram post. A pure
    state transform (no renderer call) — the images were already generated + reviewed, so this just
    marks the result `rendered` (or keeps placeholder/error) for the `marketing_render` card."""

    def finalize_post(state) -> dict:
        stills = state.get("render_stills") or {}
        has_images = any(s.get("image_url") for s in (stills.get("shots") or []))
        status = "rendered" if has_images else stills.get("status", "placeholder")
        return {"render_result": {**stills, "status": status}}

    return finalize_post
