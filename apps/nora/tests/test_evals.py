"""Tests for the evaluation harness (M5), all offline.

The deterministic evaluators are tested directly against the bundled DB; both suite runners are
driven end-to-end with injected fake models (no API key), proving the harness wiring, the
derived-truth comparison, and the marketing guardrails + judge plumbing.
"""

from __future__ import annotations

import json

from evals.evaluators import (
    JudgeScore,
    answer_correct,
    check_guardrails,
    compute_reference_answer,
    count_tool_calls,
    recovered,
    valid_sql,
)
from evals.run_evals import run_analytics_suite, run_marketing_suite
from langchain_core.messages import AIMessage, ToolMessage

from nora.config import get_settings
from nora.services.spice_db import build_spice_db
from tests.fakes import ScriptedChatModel, ScriptedStructuredModel, ai_final, ai_tool_call
from tests.test_marketing_graph import _passing_model

_A01_SQL = (
    "SELECT p.name FROM order_items oi JOIN orders o ON o.order_id=oi.order_id "
    "JOIN products p ON p.product_id=oi.product_id WHERE o.status!='cancelled' "
    "GROUP BY p.product_id ORDER BY SUM(oi.quantity*oi.unit_price_lkr) DESC LIMIT 1"
)


def _db():
    return build_spice_db(get_settings())


# --- deterministic evaluators ---------------------------------------------------------


def test_compute_reference_answer_text_and_number():
    db = _db()
    assert compute_reference_answer(db, _A01_SQL, "text") == "Ceylon Cinnamon (Alba)"
    n = compute_reference_answer(db, "SELECT COUNT(*) FROM products", "number")
    assert n == 18.0


def test_answer_correct_number_tolerance():
    assert answer_correct("We sold about 1,500 orders.", 1500, "number")
    assert answer_correct("Total is LKR 617536.", 617536, "number")
    assert not answer_correct("Around 900.", 1500, "number")


def test_answer_correct_text_overlap():
    assert answer_correct("The top product is Ceylon Cinnamon (Alba).", "Ceylon Cinnamon (Alba)", "text")
    assert answer_correct("Colombo has the most.", "Colombo", "text")
    assert not answer_correct("It is Galle.", "Colombo", "text")


def test_valid_sql_and_recovered_on_trajectory():
    err = ToolMessage(content="Your query failed: no such column: bogus", name="run_sql", tool_call_id="1")
    ok = ToolMessage(content="name | rev\nX | 1\n(1 row(s))", name="run_sql", tool_call_id="2")
    assert valid_sql([err, ok])  # last run succeeded
    assert not valid_sql([ok, err])  # last run failed
    assert recovered([err, ok])  # error then success
    assert not recovered([ok])  # never errored


def test_count_tool_calls():
    msgs = [
        ai_tool_call("run_sql", {"query": "SELECT 1"}, "1"),
        ToolMessage(content="ok", name="run_sql", tool_call_id="1"),
        AIMessage(content="done"),
    ]
    assert count_tool_calls(msgs) == 1


def test_check_guardrails_pass_and_fail():
    from nora.schemas import ScriptBeat, Shot, ShotPrompt, VideoBrief

    db = _db()
    good = VideoBrief(
        product_name="Ceylon Cinnamon (Alba)",
        concept="origin story",
        hook="Real Matale cinnamon",
        target_duration_s=30,
        script_beats=[
            ScriptBeat(t_start_s=0, t_end_s=3, voiceover="From Matale, with love."),
            ScriptBeat(t_start_s=3, t_end_s=30, voiceover="Grate it fresh."),
        ],
        shots=[Shot(index=0, scene_description="a", duration_s=15), Shot(index=1, scene_description="b", duration_s=15)],
        shot_prompts=[ShotPrompt(index=0, t2v_prompt="x"), ShotPrompt(index=1, t2v_prompt="y")],
        cta="Shop now",
        music_mood="warm",
        hashtags=["#CurryNomad"],
        product_facts_used=["Ceylon Cinnamon (Alba)", "origin: Matale", "blend"],
    )
    passed, failures = check_guardrails(good, db)
    assert passed, failures

    bad = good.model_copy(update={"target_duration_s": 60, "cta": "", "product_facts_used": ["nope"]})
    passed2, failures2 = check_guardrails(bad, db)
    assert not passed2
    assert "target_duration_out_of_range" in failures2
    assert "cta_empty" in failures2
    assert "grounding_name_missing" in failures2


# --- suite runners (injected fakes) ---------------------------------------------------


def test_run_analytics_suite_offline(tmp_path):
    dataset = tmp_path / "a.jsonl"
    dataset.write_text(
        json.dumps(
            {"id": "t1", "question": "Top product?", "reference_sql": _A01_SQL,
             "answer_type": "text", "expects_recovery": False}
        )
        + "\n"
    )
    model = ScriptedChatModel(
        [ai_tool_call("run_sql", {"query": _A01_SQL}, "1"), ai_final("It's Ceylon Cinnamon (Alba).")]
    )
    out = run_analytics_suite(model=model, dataset_path=dataset)
    assert out["metrics"]["accuracy"] == 1.0
    assert out["metrics"]["sql_validity"] == 1.0
    assert out["items"][0]["correct"]


def test_analytics_suite_pushes_langfuse_scores(tmp_path, monkeypatch):
    """When a Langfuse handler is active, the suite attaches the deterministic metrics as scores.

    Fully offline: both the handler and `score_trace` are faked, so no `langfuse` package or server
    is touched — this pins the runner's auto-on scoring wiring (trace id + score names + data types).
    """
    import evals.run_evals as run_evals

    dataset = tmp_path / "a.jsonl"
    dataset.write_text(
        json.dumps(
            {"id": "t1", "question": "Top product?", "reference_sql": _A01_SQL,
             "answer_type": "text", "expects_recovery": False}
        )
        + "\n"
    )
    model = ScriptedChatModel(
        [ai_tool_call("run_sql", {"query": _A01_SQL}, "1"), ai_final("It's Ceylon Cinnamon (Alba).")]
    )

    from langchain_core.callbacks import BaseCallbackHandler

    class _FakeHandler(BaseCallbackHandler):  # a valid no-op callback, so attaching it is harmless
        last_trace_id = "trace-xyz"

    pushed: list[tuple] = []
    monkeypatch.setattr(run_evals, "get_langfuse_handler", lambda: _FakeHandler())
    monkeypatch.setattr(
        run_evals,
        "score_trace",
        lambda trace_id, name, value, **kw: pushed.append((trace_id, name, value, kw.get("data_type"))),
    )

    run_evals.run_analytics_suite(model=model, dataset_path=dataset)

    assert {name for _, name, _, _ in pushed} == {"eval-correct", "eval-valid-sql", "eval-tool-calls"}
    assert all(trace_id == "trace-xyz" for trace_id, *_ in pushed)
    by_name = {name: (value, dtype) for _, name, value, dtype in pushed}
    assert by_name["eval-correct"] == (1, "BOOLEAN")  # bool coerced to int for the BOOLEAN score
    assert by_name["eval-tool-calls"] == (1.0, "NUMERIC")


def test_run_analytics_suite_measures_recovery(tmp_path):
    dataset = tmp_path / "rec.jsonl"
    dataset.write_text(
        json.dumps(
            {"id": "r1", "question": "units?",
             "reference_sql": "SELECT SUM(oi.quantity) FROM order_items oi",
             "answer_type": "number", "expects_recovery": True}
        )
        + "\n"
    )
    truth = compute_reference_answer(_db(), "SELECT SUM(oi.quantity) FROM order_items oi", "number")
    model = ScriptedChatModel(
        [
            ai_tool_call("run_sql", {"query": "SELECT bogus FROM order_items"}, "1"),  # fails
            ai_tool_call("run_sql", {"query": "SELECT SUM(quantity) FROM order_items"}, "2"),  # ok
            ai_final(f"We sold {int(truth)} units."),
        ]
    )
    out = run_analytics_suite(model=model, dataset_path=dataset)
    assert out["metrics"]["recovery_rate"] == 1.0
    assert out["items"][0]["recovered"]
    assert out["items"][0]["correct"]


def test_run_marketing_suite_offline():
    judge = ScriptedStructuredModel(
        {JudgeScore: [JudgeScore(brand_voice=5, coherence=4, justification="warm and on-brand")]}
    )
    out = run_marketing_suite(model=_passing_model(), judge_model=judge)
    assert out["metrics"]["guardrail_pass_rate"] == 1.0
    assert out["metrics"]["judge_mean"] == 4.5
    assert out["metrics"]["n"] == 7
