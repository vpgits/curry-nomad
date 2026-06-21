"""Offline coverage for the analytics generative-UI dashboard (orchestrator._build_dashboard).

The dashboard is composed post-hoc from the agent's final answer + the SQL it ran, via a
structured-output model. We drive it with a scripted fake (no API key), the same way the
marketing tests drive their structured steps.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from nora.orchestrator import _build_dashboard
from nora.schemas import AnalyticsDashboard, DashboardStat, DashboardTable
from tests.fakes import ScriptedStructuredModel


def test_build_dashboard_from_answer_and_query_results():
    dashboard = AnalyticsDashboard(
        title="Colombo — last quarter",
        stats=[
            DashboardStat(label="Units sold", value="73"),
            DashboardStat(label="Revenue", value="LKR 105,850"),
        ],
        table=DashboardTable(columns=["Product", "Units"], rows=[["Ceylon Cinnamon (Alba)", "73"]]),
    )
    model = ScriptedStructuredModel({AnalyticsDashboard: [dashboard]})
    final = AIMessage(content="Best-seller was Ceylon Cinnamon (Alba). Units sold: 73.")
    trace = [
        {
            "calls": [
                {
                    "name": "run_sql",
                    "args": {"query": "SELECT ..."},
                    "result": "product_name|units_sold\nCeylon Cinnamon (Alba)|73",
                }
            ]
        }
    ]

    result = _build_dashboard(model, final, trace)

    assert result is not None
    assert result.title == "Colombo — last quarter"
    assert [s.value for s in result.stats] == ["73", "LKR 105,850"]
    # The SQL results the agent saw are folded into the generation prompt (grounding).
    assert any("Ceylon Cinnamon (Alba)|73" in prompt for prompt in model.prompts)


def test_build_dashboard_skips_when_nothing_dashboard_worthy():
    empty = AnalyticsDashboard(title="n/a", stats=[], table=None)
    model = ScriptedStructuredModel({AnalyticsDashboard: [empty]})
    final = AIMessage(content="The refund rate on blends is 4.2%.")

    assert _build_dashboard(model, final, trace=[]) is None


def test_build_dashboard_skips_on_empty_answer():
    model = ScriptedStructuredModel({AnalyticsDashboard: [AnalyticsDashboard(title="x")]})
    assert _build_dashboard(model, AIMessage(content=""), trace=[]) is None
