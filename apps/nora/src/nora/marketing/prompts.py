"""Marketing workflow prompts (versioned, in one place).

Each builder returns a plain string. Product facts are passed in as a dict (pulled from the
real DB row) so the copy is grounded — the eval checks those facts actually appear in the brief.
"""

from __future__ import annotations

from nora.schemas import ConceptIdea, ScriptBeat, Shot, ShotPrompt

MARKETING_PROMPT_VERSION = "v1"

# Fallback brand voice when the Store isn't wired (M2 runs before memory in M3).
DEFAULT_BRAND_VOICE = (
    "Curry Nomad is warm, a little cheeky, and proudly Sri Lankan — celebrate origin and "
    "authenticity. No generic ad-speak, no medical claims."
)

# Distinct creative angles so parallel ideation returns genuinely different concepts.
_ANGLE_SEEDS = [
    "origin story — the specific place and the people who grow it",
    "sensory — aroma, color, and the sound of cooking",
    "everyday ritual — the dish this unlocks at home",
    "heritage & pride — diaspora nostalgia, done tastefully",
    "bold contrast — supermarket blend vs. the real single-origin thing",
]

PLATFORM_RULES = (
    "Platform rules for a ~30s Instagram Reel: the hook must land in the first 3 seconds "
    "(first beat starts at 0s and ends by 3s); there must be a clear call-to-action; total "
    "duration should be 25-35s; the product's real facts (name, origin) must be used; no "
    "banned claims (no 'cure', 'guaranteed', '#1 in the world', or medical claims)."
)


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
        f"Propose ONE distinct short-video concept built around this angle: {angle}.\n"
        "Return an angle (one line), a scroll-stopping hook line, and a one-sentence rationale."
    )


def script_prompt(concept: ConceptIdea, brand_voice: str, facts: dict, target_s: float) -> str:
    return (
        f"Brand voice: {brand_voice}\n{_facts_block(facts)}\n\n"
        f"Chosen concept — angle: {concept.angle}; hook: {concept.hook}\n\n"
        f"Write a ~{target_s:.0f}s Instagram Reel voiceover script as timed beats. The first "
        "beat MUST start at 0s and deliver the hook within the first 3 seconds. Cover the "
        "product's real origin. End with a clear call-to-action beat. Keep total duration "
        "between 25 and 35 seconds. Each beat has t_start_s, t_end_s, voiceover, and optional "
        "on_screen_text. No banned claims (no cure/guaranteed/#1/medical claims)."
    )


def storyboard_prompt(script_beats: list[ScriptBeat], facts: dict) -> str:
    beats = "\n".join(f"[{b.t_start_s}-{b.t_end_s}s] {b.voiceover}" for b in script_beats)
    return (
        f"{_facts_block(facts)}\n\nScript:\n{beats}\n\n"
        "Break this script into 3-6 visual shots that cover the whole duration. For each shot "
        "give an index (starting at 0), a concrete scene_description, and a duration_s. The "
        "shot durations should roughly sum to the script length."
    )


def shot_prompt_prompt(shot: Shot, brand_voice: str, facts: dict) -> str:
    return (
        f"Brand voice: {brand_voice}\n{_facts_block(facts)}\n\n"
        f"Write a single vivid text-to-video generation prompt for this shot "
        f"(#{shot.index}, {shot.duration_s}s): {shot.scene_description}\n"
        "Describe subject, setting, lighting, camera move, and mood in one rich paragraph. "
        "Make it authentically Sri Lankan. Output only the prompt text."
    )


def critique_prompt(
    script_beats: list[ScriptBeat], shot_prompts: list[ShotPrompt], brand_voice: str
) -> str:
    beats = "\n".join(f"[{b.t_start_s}-{b.t_end_s}s] {b.voiceover}" for b in script_beats)
    shots = "\n".join(f"#{p.index}: {p.t2v_prompt}" for p in shot_prompts)
    return (
        f"You are a strict brand editor.\nBrand voice: {brand_voice}\n{PLATFORM_RULES}\n\n"
        f"Script beats:\n{beats}\n\nShot prompts:\n{shots}\n\n"
        "Judge whether this draft is on-brand and meets the platform rules. Set passed=true "
        "only if it clearly does. If not, list concrete issues and actionable suggestions."
    )


def revise_prompt(script_beats: list[ScriptBeat], issues: list[str], suggestions: list[str]) -> str:
    beats = "\n".join(f"[{b.t_start_s}-{b.t_end_s}s] {b.voiceover}" for b in script_beats)
    fixes = "\n".join(f"- {s}" for s in (suggestions or issues))
    return (
        f"Revise this Reel script to address the feedback while keeping it ~30s and on-brand.\n"
        f"Current script:\n{beats}\n\nFeedback to apply:\n{fixes}\n\n"
        "Return the full revised set of timed beats (hook still in the first 3 seconds)."
    )


def brief_copy_prompt(concept: ConceptIdea, brand_voice: str, facts: dict) -> str:
    return (
        f"Brand voice: {brand_voice}\n{_facts_block(facts)}\n"
        f"Concept hook: {concept.hook}\n\n"
        "Write the finishing copy for this Reel: a short call-to-action (cta), a music_mood "
        "(a few words), and 4-6 relevant hashtags (no spaces, include the brand and origin). "
        "No banned claims."
    )
