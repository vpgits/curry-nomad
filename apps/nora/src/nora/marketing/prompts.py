"""Marketing workflow prompts (versioned, in one place).

Each builder returns a plain string. Product facts are passed in as a dict (pulled from the
real DB row) so the copy is grounded — the eval checks those facts actually appear in the post.
"""

from __future__ import annotations

from nora.schemas import ConceptIdea, Shot, ShotPrompt

MARKETING_PROMPT_VERSION = "v2"

# Fallback brand voice when the Store isn't wired (M2 runs before memory in M3).
DEFAULT_BRAND_VOICE = (
    "Curry Nomad is warm, a little cheeky, and proudly Sri Lankan — celebrate origin and "
    "authenticity. No generic ad-speak, no medical claims."
)

# Distinct creative angles so parallel ideation returns genuinely different concepts.
_ANGLE_SEEDS = [
    "origin story — the specific place and the people who grow it",
    "sensory — aroma, color, and the textures of cooking",
    "everyday ritual — the dish this unlocks at home",
    "heritage & pride — diaspora nostalgia, done tastefully",
    "bold contrast — supermarket blend vs. the real single-origin thing",
]

PLATFORM_RULES = (
    "Platform rules for an Instagram image post: a scroll-stopping hook in the caption's first "
    "line; a clear call-to-action; the product's real facts (name, origin) must be used; each "
    "image has a short on-screen text line; no banned claims (no 'cure', 'guaranteed', "
    "'#1 in the world', or medical claims)."
)

# Caption length by operator-chosen verbosity (the copy-gate control).
_VERBOSITY = {
    "concise": "Keep the caption very short — 1-2 punchy lines.",
    "standard": "Keep the caption around 3 sentences.",
    "detailed": "Write a richer, storytelling caption of 4-6 sentences.",
}


def _facts_block(facts: dict) -> str:
    return (
        f"Product: {facts.get('name')} | category: {facts.get('category')} | "
        f"origin: {facts.get('origin')} | pack: {facts.get('grams')}g | "
        f"price: LKR {facts.get('unit_price_lkr')}"
    )


def ideate_prompt(brand_voice: str, facts: dict, request: str, seed_index: int) -> str:
    angle = _ANGLE_SEEDS[seed_index % len(_ANGLE_SEEDS)]
    return (
        f"You are a creative director for Curry Nomad.\nBrand voice: {brand_voice}\n"
        f"{_facts_block(facts)}\nRequest: {request}\n\n"
        f"Propose ONE distinct Instagram post concept built around this angle: {angle}.\n"
        "Return an angle (one line), a scroll-stopping hook line, and a one-sentence rationale."
    )


def copy_prompt(
    concept: ConceptIdea,
    brand_voice: str,
    facts: dict,
    *,
    verbosity: str = "standard",
    num_images: int = 4,
) -> str:
    length = _VERBOSITY.get(verbosity, _VERBOSITY["standard"])
    return (
        f"Brand voice: {brand_voice}\n{_facts_block(facts)}\n\n"
        f"Chosen concept — angle: {concept.angle}; hook: {concept.hook}\n\n"
        "Write the copy for an Instagram image post:\n"
        "- caption: the post caption body. Open with the hook on the first line, then the "
        f"product's real origin story, and end with a clear call-to-action. {length}\n"
        f"- on_screen_texts: EXACTLY {num_images} short on-screen text lines (a few words each), "
        "one per intended image, in order — the first carries the hook.\n"
        "No banned claims (no cure/guaranteed/#1/medical claims)."
    )


def storyboard_prompt(caption: str, on_screen_texts: list[str], facts: dict) -> str:
    lines = "\n".join(f"{i}: {t}" for i, t in enumerate(on_screen_texts))
    n = len(on_screen_texts)
    return (
        f"{_facts_block(facts)}\n\nPost caption:\n{caption}\n\nOn-screen text lines:\n{lines}\n\n"
        f"Produce EXACTLY {n} still images, one per on-screen text line above. For each, give "
        "an index (starting at 0, matching the line), a concrete scene_description of the image, "
        "and the matching on_screen_text."
    )


def shot_prompt_prompt(shot: Shot, brand_voice: str, facts: dict) -> str:
    return (
        f"Brand voice: {brand_voice}\n{_facts_block(facts)}\n\n"
        f"Write a single vivid text-to-image generation prompt for this image "
        f"(#{shot.index}): {shot.scene_description}\n"
        "Describe subject, setting, lighting, composition, and mood in one rich paragraph. "
        "Make it authentically Sri Lankan. Output only the prompt text."
    )


def critique_prompt(caption: str, shot_prompts: list[ShotPrompt], brand_voice: str) -> str:
    shots = "\n".join(f"#{p.index}: {p.image_prompt}" for p in shot_prompts)
    return (
        f"You are a strict brand editor.\nBrand voice: {brand_voice}\n{PLATFORM_RULES}\n\n"
        f"Post caption:\n{caption}\n\nImage prompts:\n{shots}\n\n"
        "Judge whether this draft is on-brand and meets the platform rules. Set passed=true "
        "only if it clearly does. If not, list concrete issues and actionable suggestions."
    )


def revise_prompt(
    caption: str,
    issues: list[str],
    suggestions: list[str],
    *,
    verbosity: str = "standard",
    num_images: int = 4,
) -> str:
    fixes = "\n".join(f"- {s}" for s in (suggestions or issues))
    length = _VERBOSITY.get(verbosity, _VERBOSITY["standard"])
    return (
        "Revise this Instagram post copy to address the feedback while keeping it on-brand.\n"
        f"Current caption:\n{caption}\n\nFeedback to apply:\n{fixes}\n\n"
        f"{length} Return the full revised caption (hook still in the first line) and EXACTLY "
        f"{num_images} on-screen text lines."
    )


def brief_copy_prompt(concept: ConceptIdea, brand_voice: str, facts: dict) -> str:
    return (
        f"Brand voice: {brand_voice}\n{_facts_block(facts)}\n"
        f"Concept hook: {concept.hook}\n\n"
        "Write the finishing copy for this Instagram post: a short call-to-action (cta) and "
        "4-6 relevant hashtags (no spaces, include the brand and origin). No banned claims."
    )
