"""Run the evaluation suites.

    uv run python apps/nora/evals/run_evals.py --suite all          # analytics + marketing, offline
    uv run python apps/nora/evals/run_evals.py --suite analytics
    uv run python apps/nora/evals/run_evals.py --suite marketing --langsmith

Offline by default: it runs the actual graphs against the bundled DB with the configured model
(so it needs a provider key, e.g. OPENAI_API_KEY — but no external data and no LangSmith). The
suite functions accept injected models, which is how the harness itself is tested without a key.
`--langsmith` additionally pushes the analytics suite to LangSmith `evaluate` for the dashboard.

Langfuse tracing is *auto-on* (no flag), mirroring the chat path in `nora.app`: when
`LANGFUSE_PUBLIC_KEY` is set, each eval item is traced under a per-suite session, and the metrics
that the run already computes — deterministic checks (`eval-correct`, `eval-valid-sql`,
`eval-recovered`, `eval-tool-calls`) and the LLM-judge axes (`eval-guardrails-passed`,
`judge-brand-voice`, `judge-coherence`) — are attached to that trace as Langfuse *scores* (the
skill's "capture as scores" best practice). Unlike `--langsmith`, this needs no extra runs: it
piggybacks on the graph invocations the eval already makes. A no-op when Langfuse isn't configured.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Make `nora` (src/) and `evals` (repo root) importable when run as a plain script.
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

from langchain.chat_models import init_chat_model  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402

from evals.evaluators import (  # noqa: E402
    answer_correct,
    check_guardrails,
    compute_reference_answer,
    count_tool_calls,
    judge_brief,
    recovered,
    valid_sql,
)
from nora.analytics.graph import build_analytics_graph  # noqa: E402
from nora.config import get_settings  # noqa: E402
from nora.marketing.graph import build_marketing_graph, initial_marketing_state  # noqa: E402
from nora.marketing.prompts import DEFAULT_BRAND_VOICE  # noqa: E402
from nora.observability import (  # noqa: E402
    flush_langfuse,
    get_langfuse_handler,
    get_logger,
    score_trace,
    setup_logging,
)
from nora.schemas import VideoBrief  # noqa: E402
from nora.services.spice_db import build_spice_db  # noqa: E402

log = get_logger(__name__)

ANALYTICS_DATASET = _ROOT / "evals" / "analytics_dataset.jsonl"
MARKETING_DATASET = _ROOT / "evals" / "marketing_dataset.jsonl"

# Teaching targets (illustrative, model-dependent) — from specs/02_data_and_evals.md §3.
TARGETS = {
    "analytics_accuracy": 0.80,
    "marketing_guardrail_pass_rate": 0.90,
    "marketing_judge_mean": 4.0,
}

_PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
    "google": "GOOGLE_API_KEY",
}


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def _provider_key_present(model: str) -> bool:
    provider = model.split(":")[0] if ":" in model else "openai"
    env = _PROVIDER_KEY_ENV.get(provider)
    return bool(os.getenv(env)) if env else True


def _langfuse_config(handler, *, suite: str, item_id: str) -> dict | None:
    """Run config that routes one eval item's trace to Langfuse, or ``None`` when tracing is off.

    Mirrors `nora.app`: the SDK v3 LangChain handler reads trace attributes off the run config's
    `metadata` (NOT constructor args). Grouping every item of a suite under one `langfuse_session_id`
    lets the Sessions view show the whole eval run together; the per-item `langfuse_trace_name` keeps
    traces findable. Returns ``None`` (so `graph.invoke(inputs, None)` runs untraced) when Langfuse
    isn't configured, so the offline test harness is unaffected.
    """
    if handler is None:
        return None
    return {
        "callbacks": [handler],
        "metadata": {
            "langfuse_session_id": f"eval-{suite}",
            "langfuse_tags": ["nora", "eval", suite],
            "langfuse_trace_name": f"eval-{suite}-{item_id}",
        },
    }


# --- analytics suite ------------------------------------------------------------------


def run_analytics_suite(*, settings=None, model=None, dataset_path: Path = ANALYTICS_DATASET) -> dict:
    settings = settings or get_settings()
    spice_db = build_spice_db(settings)
    graph = build_analytics_graph(settings=settings, model=model)  # questions carry their own definitions
    handler = get_langfuse_handler()  # auto-on; None (and untraced) when Langfuse isn't configured

    items = []
    for row in _load_jsonl(dataset_path):
        config = _langfuse_config(handler, suite="analytics", item_id=row["id"])
        result = graph.invoke({"messages": [HumanMessage(content=row["question"])]}, config)
        answer = result["messages"][-1].content or ""
        reference = compute_reference_answer(spice_db, row["reference_sql"], row["answer_type"])
        record = {
            "id": row["id"],
            "correct": answer_correct(answer, reference, row["answer_type"]),
            "valid_sql": valid_sql(result["messages"]),
            "expects_recovery": row["expects_recovery"],
            "recovered": recovered(result["messages"]),
            "tool_calls": count_tool_calls(result["messages"]),
            "reference": reference,
            "answer": answer,
        }
        log.info("eval.scored", suite="analytics", id=record["id"], correct=record["correct"])
        items.append(record)

        if handler is not None:  # attach the deterministic metrics as scores on this item's trace
            trace_id = handler.last_trace_id
            score_trace(trace_id, "eval-correct", int(record["correct"]), data_type="BOOLEAN")
            score_trace(trace_id, "eval-valid-sql", int(record["valid_sql"]), data_type="BOOLEAN")
            if record["expects_recovery"]:  # only meaningful for the self-correction items
                score_trace(trace_id, "eval-recovered", int(record["recovered"]), data_type="BOOLEAN")
            score_trace(trace_id, "eval-tool-calls", float(record["tool_calls"]), data_type="NUMERIC")

    recovery_items = [i for i in items if i["expects_recovery"]]
    metrics = {
        "accuracy": _mean(i["correct"] for i in items),
        "sql_validity": _mean(i["valid_sql"] for i in items),
        "recovery_rate": _mean(i["recovered"] and i["correct"] for i in recovery_items)
        if recovery_items
        else None,
        "avg_tool_calls": _mean(i["tool_calls"] for i in items),
        "n": len(items),
    }
    return {"items": items, "metrics": metrics}


# --- marketing suite ------------------------------------------------------------------


def run_marketing_suite(
    *, settings=None, model=None, judge_model=None, dataset_path: Path = MARKETING_DATASET
) -> dict:
    settings = settings or get_settings()
    spice_db = build_spice_db(settings)
    # auto_approve so the HITL gate doesn't block the unattended batch.
    graph = build_marketing_graph(
        settings=settings, model=model, spice_db=spice_db, auto_approve=True
    )
    handler = get_langfuse_handler()  # auto-on; None (and untraced) when Langfuse isn't configured

    items = []
    for row in _load_jsonl(dataset_path):
        config = _langfuse_config(handler, suite="marketing", item_id=row["id"])
        result = graph.invoke(initial_marketing_state(row["request"], row["product_name"]), config)
        brief = VideoBrief(**result["brief"])  # state stores a dict; rehydrate for the evaluators
        passed, failures = check_guardrails(brief, spice_db)
        score = judge_brief(brief, DEFAULT_BRAND_VOICE, judge_model) if judge_model else None
        record = {
            "id": row["id"],
            "guardrails_passed": passed,
            "failures": failures,
            "judge": score.model_dump() if score else None,
        }
        log.info(
            "eval.scored",
            suite="marketing",
            id=record["id"],
            guardrails_passed=passed,
            judge=(score.brand_voice + score.coherence) / 2 if score else None,
        )
        items.append(record)

        if handler is not None:  # guardrail verdict + LLM-judge axes as scores on this item's trace
            trace_id = handler.last_trace_id
            score_trace(
                trace_id, "eval-guardrails-passed", int(passed), data_type="BOOLEAN",
                comment=", ".join(failures) if failures else None,
            )
            if score is not None:  # the judge's one-line rationale rides along as the score comment
                score_trace(trace_id, "judge-brand-voice", float(score.brand_voice),
                            data_type="NUMERIC", comment=score.justification)
                score_trace(trace_id, "judge-coherence", float(score.coherence),
                            data_type="NUMERIC", comment=score.justification)

    judged = [i["judge"] for i in items if i["judge"]]
    metrics = {
        "guardrail_pass_rate": _mean(i["guardrails_passed"] for i in items),
        "judge_mean": _mean((j["brand_voice"] + j["coherence"]) / 2 for j in judged)
        if judged
        else None,
        "n": len(items),
    }
    return {"items": items, "metrics": metrics}


def _mean(values) -> float:
    values = [float(v) for v in values]
    return round(sum(values) / len(values), 3) if values else 0.0


# --- reporting ------------------------------------------------------------------------


def print_report(results: dict) -> None:
    """Human-readable report (this is the deliverable, hence print, not the logger)."""
    if "analytics" in results:
        r = results["analytics"]
        print("\n=== Analytics suite (deterministic / ground truth) ===")
        for i in r["items"]:
            flag = "OK " if i["correct"] else "XX "
            rec = " [recovered]" if i["expects_recovery"] and i["recovered"] else ""
            print(f"  {flag}{i['id']}: correct={i['correct']} valid_sql={i['valid_sql']} "
                  f"tools={i['tool_calls']}{rec}")
        m = r["metrics"]
        print(f"  -> accuracy={m['accuracy']} (target {TARGETS['analytics_accuracy']}) | "
              f"sql_validity={m['sql_validity']} | recovery_rate={m['recovery_rate']} | "
              f"avg_tool_calls={m['avg_tool_calls']}")

    if "marketing" in results:
        r = results["marketing"]
        print("\n=== Marketing suite (LLM-judge + guardrails) ===")
        for i in r["items"]:
            flag = "OK " if i["guardrails_passed"] else "XX "
            judge = i["judge"]
            js = f" judge(voice={judge['brand_voice']},coherence={judge['coherence']})" if judge else ""
            fails = f" failures={i['failures']}" if i["failures"] else ""
            print(f"  {flag}{i['id']}: guardrails={i['guardrails_passed']}{js}{fails}")
        m = r["metrics"]
        print(f"  -> guardrail_pass_rate={m['guardrail_pass_rate']} "
              f"(target {TARGETS['marketing_guardrail_pass_rate']}) | "
              f"judge_mean={m['judge_mean']} (target {TARGETS['marketing_judge_mean']})")
    print("\n(Targets are illustrative and model-dependent.)")


# --- optional LangSmith push (analytics suite) ----------------------------------------


def run_langsmith_analytics(settings) -> None:
    """Best-effort push of the analytics suite to LangSmith `evaluate` for the dashboard view.

    Requires LANGSMITH_API_KEY. The ground truth is derived from each item's reference_sql, so
    correctness is computed inside the evaluator — no hand-labeled answers needed."""
    if not os.getenv("LANGSMITH_API_KEY"):
        print("\n--langsmith requires LANGSMITH_API_KEY; skipping the dashboard push.")
        return

    from langsmith import Client, evaluate

    client = Client()
    spice_db = build_spice_db(settings)
    rows = _load_jsonl(ANALYTICS_DATASET)

    dataset_name = "curry-nomad-analytics"
    if not client.has_dataset(dataset_name=dataset_name):
        dataset = client.create_dataset(dataset_name=dataset_name)
        client.create_examples(
            dataset_id=dataset.id,
            inputs=[{"question": r["question"]} for r in rows],
            outputs=[
                {"reference_sql": r["reference_sql"], "answer_type": r["answer_type"]} for r in rows
            ],
        )

    graph = build_analytics_graph(settings=settings)

    def target(inputs: dict) -> dict:
        result = graph.invoke({"messages": [HumanMessage(content=inputs["question"])]})
        return {"answer": result["messages"][-1].content or ""}

    def correctness(outputs: dict, reference_outputs: dict) -> dict:
        truth = compute_reference_answer(
            spice_db, reference_outputs["reference_sql"], reference_outputs["answer_type"]
        )
        return {
            "key": "answer_correct",
            "score": float(answer_correct(outputs["answer"], truth, reference_outputs["answer_type"])),
        }

    evaluate(target, data=dataset_name, evaluators=[correctness], client=client,
             experiment_prefix="curry-nomad-analytics")
    print(f"\nPushed analytics evaluate run to LangSmith dataset '{dataset_name}'.")


# --- CLI ------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Curry Nomad eval suites.")
    parser.add_argument("--suite", choices=["analytics", "marketing", "all"], default="all")
    parser.add_argument("--langsmith", action="store_true", help="also push analytics to LangSmith")
    args = parser.parse_args(argv)

    setup_logging(json_logs=False)
    settings = get_settings()
    if not _provider_key_present(settings.model):
        provider = settings.model.split(":")[0]
        env = _PROVIDER_KEY_ENV.get(provider, "OPENAI_API_KEY")
        print(f"No provider key found. Set {env} in your environment/.env to run the evals "
              f"(model={settings.model}).")
        return 2

    analytics_model = init_chat_model(settings.model, temperature=0)
    marketing_model = init_chat_model(settings.model, temperature=0.7)
    judge_model = init_chat_model(settings.model, temperature=0)

    results: dict = {}
    try:
        if args.suite in ("analytics", "all"):
            results["analytics"] = run_analytics_suite(settings=settings, model=analytics_model)
        if args.suite in ("marketing", "all"):
            results["marketing"] = run_marketing_suite(
                settings=settings, model=marketing_model, judge_model=judge_model
            )
    finally:
        # The Langfuse SDK batches events/scores in the background; flush before this short-lived
        # process exits or the traces may never be sent. A no-op when Langfuse isn't configured.
        flush_langfuse()
    print_report(results)

    if args.langsmith and args.suite in ("analytics", "all"):
        run_langsmith_analytics(settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
