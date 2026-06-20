"""Evaluators for both suites.

Analytics (deterministic): derive the ground truth by running the item's `reference_sql`
against the bundled DB, then compare the agent's final answer to it — the truth is never
hand-typed. Plus trajectory metrics: was the final SQL valid, and (for recovery items) did the
agent hit a SQL error and then recover?

Marketing (judge + guardrails): hard structural/grounding/safety checks on the VideoBrief, plus
an LLM-as-judge rubric for brand voice and coherence.
"""

from __future__ import annotations

import re

from langchain_core.messages import AIMessage, ToolMessage
from pydantic import BaseModel, Field

from nora.marketing.nodes import lookup_product_facts
from nora.schemas import VideoBrief

# Substrings that signal a run_sql ToolMessage was the error/repair hint (see handle_sql_error).
_SQL_ERROR_MARKER = "your query failed"

BANNED_CLAIMS = ["cure", "guaranteed", "#1 in the world", "miracle", "clinically proven", "cures"]


# --- analytics: derived ground truth --------------------------------------------------


def compute_reference_answer(spice_db, reference_sql: str, answer_type: str):
    """Run the reference SQL and extract the canonical answer (number / text / set)."""
    result = spice_db.run_sql(reference_sql)
    rows = result["rows"]
    if not rows:
        return None
    if answer_type == "number":
        value = rows[0][-1]  # the numeric answer is the last column
        return float(value) if value is not None else None
    if answer_type == "text":
        return str(rows[0][0])  # the text answer is the first column
    if answer_type == "list":
        return {str(r[0]) for r in rows}
    raise ValueError(f"unknown answer_type: {answer_type}")


_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def _numbers_in(text: str) -> list[float]:
    out = []
    for token in _NUMBER_RE.findall(text):
        try:
            out.append(float(token.replace(",", "")))
        except ValueError:
            continue
    return out


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", text.lower())


def answer_correct(agent_text: str, reference, answer_type: str) -> bool:
    """Compare the agent's free-text answer to the derived truth."""
    if reference is None:
        return False
    if answer_type == "number":
        ref = float(reference)
        tol = max(0.5, abs(ref) * 0.01)  # 1% relative, or 0.5 absolute (rounding/percentages)
        return any(abs(n - ref) <= tol for n in _numbers_in(agent_text))
    if answer_type == "text":
        norm_agent = _normalize(agent_text)
        norm_ref = _normalize(str(reference)).strip()
        if norm_ref and norm_ref in norm_agent:
            return True
        ref_words = [w for w in norm_ref.split() if w]
        if not ref_words:
            return False
        hits = sum(1 for w in ref_words if w in norm_agent)
        return hits / len(ref_words) >= 0.6  # lenient word overlap
    if answer_type == "list":
        norm_agent = _normalize(agent_text)
        return all(_normalize(str(item)).strip() in norm_agent for item in reference)
    raise ValueError(f"unknown answer_type: {answer_type}")


# --- analytics: trajectory metrics ----------------------------------------------------


def _run_sql_tool_messages(messages: list) -> list[ToolMessage]:
    return [m for m in messages if isinstance(m, ToolMessage) and m.name == "run_sql"]


def _is_sql_error(msg: ToolMessage) -> bool:
    return _SQL_ERROR_MARKER in str(msg.content).lower()


def valid_sql(messages: list) -> bool:
    """True if the agent ran at least one run_sql and its last run_sql succeeded."""
    runs = _run_sql_tool_messages(messages)
    return bool(runs) and not _is_sql_error(runs[-1])


def recovered(messages: list) -> bool:
    """True if a run_sql error was followed by a later successful run_sql (self-correction)."""
    runs = _run_sql_tool_messages(messages)
    saw_error = False
    for msg in runs:
        if _is_sql_error(msg):
            saw_error = True
        elif saw_error:
            return True
    return False


def count_tool_calls(messages: list) -> int:
    return sum(len(m.tool_calls) for m in messages if isinstance(m, AIMessage) and m.tool_calls)


# --- marketing: deterministic guardrails ----------------------------------------------


def check_guardrails(brief: VideoBrief, spice_db) -> tuple[bool, list[str]]:
    """Hard checks on the VideoBrief. Returns (passed, list_of_failures)."""
    failures: list[str] = []

    if not (25 <= brief.target_duration_s <= 35):
        failures.append("target_duration_out_of_range")
    if not (2 <= len(brief.shots) <= 8):
        failures.append("shot_count_out_of_range")
    if len(brief.shot_prompts) != len(brief.shots):
        failures.append("shot_prompts_count_mismatch")

    beats = brief.script_beats
    if not beats or beats[0].t_start_s != 0 or not beats[0].voiceover.strip() or beats[0].t_end_s > 3:
        failures.append("hook_missing_or_late")
    if not brief.cta.strip():
        failures.append("cta_empty")

    # Product grounding: the real name + origin must appear in product_facts_used.
    facts_text = " ".join(brief.product_facts_used).lower()
    product = lookup_product_facts(spice_db, brief.product_name)
    if product["name"].lower() not in facts_text:
        failures.append("grounding_name_missing")
    if str(product["origin"]).lower() not in facts_text:
        failures.append("grounding_origin_missing")

    # Banned claims in any voiceover / on-screen text.
    copy = " ".join(b.voiceover for b in beats)
    copy += " " + " ".join(b.on_screen_text or "" for b in beats)
    if any(term in copy.lower() for term in BANNED_CLAIMS):
        failures.append("banned_claim")

    return (len(failures) == 0, failures)


# --- marketing: LLM-as-judge ----------------------------------------------------------


class JudgeScore(BaseModel):
    brand_voice: int = Field(ge=1, le=5, description="adherence to the brand voice, 1-5")
    coherence: int = Field(ge=1, le=5, description="coherence + hook quality, 1-5")
    justification: str


JUDGE_RUBRIC = (
    "You are a brand editor for Curry Nomad, a Sri Lankan spice business whose voice is warm, "
    "a little cheeky, and proudly Sri Lankan (celebrating origin/authenticity, never generic AI "
    "ad copy, never medical claims). Score the creative on two axes, 1-5:\n"
    "- brand_voice: 5 = unmistakably warm, cheeky, proudly Sri Lankan and grounded in the real "
    "product/origin; 1 = generic, off-brand, or claim-y.\n"
    "- coherence: 5 = a tight, single-idea reel with a strong 3-second hook and clear CTA; "
    "1 = incoherent or no hook.\n"
    "Give a one-line justification."
)


def judge_brief(brief: VideoBrief, brand_voice: str, judge_model) -> JudgeScore:
    """Score the brief with an LLM judge (structured output)."""
    beats = "\n".join(f"[{b.t_start_s}-{b.t_end_s}s] {b.voiceover}" for b in brief.script_beats)
    prompt = (
        f"{JUDGE_RUBRIC}\n\nBrand voice reference:\n{brand_voice}\n\n"
        f"Creative for {brief.product_name}\nConcept: {brief.concept}\nHook: {brief.hook}\n"
        f"CTA: {brief.cta}\nScript:\n{beats}\n"
    )
    return judge_model.with_structured_output(JudgeScore).invoke(prompt)
