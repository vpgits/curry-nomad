"""Offline coverage for the analytics generative-UI dashboard (orchestrator._build_dashboard).

The dashboard is composed post-hoc from the agent's final answer + the SQL it ran, via a
structured-output model. We drive it with a scripted fake (no API key), the same way the
marketing tests drive their structured steps.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from nora.orchestrator import _build_dashboard, _sql_results_from_messages
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
    answer = "Best-seller was Ceylon Cinnamon (Alba). Units sold: 73."
    query_results = "product_name|units_sold\nCeylon Cinnamon (Alba)|73"

    result = _build_dashboard(model, answer, query_results)

    assert result is not None
    assert result.title == "Colombo — last quarter"
    assert [s.value for s in result.stats] == ["73", "LKR 105,850"]
    # The SQL results the agent saw are folded into the generation prompt (grounding).
    assert any("Ceylon Cinnamon (Alba)|73" in prompt for prompt in model.prompts)


def test_build_dashboard_skips_when_nothing_dashboard_worthy():
    empty = AnalyticsDashboard(title="n/a", stats=[], table=None)
    model = ScriptedStructuredModel({AnalyticsDashboard: [empty]})

    assert _build_dashboard(model, "The refund rate on blends is 4.2%.", "") is None


def test_build_dashboard_skips_on_empty_answer():
    model = ScriptedStructuredModel({AnalyticsDashboard: [AnalyticsDashboard(title="x")]})
    assert _build_dashboard(model, "", "") is None


def test_sql_results_from_messages_pairs_run_sql_to_its_result():
    """The agent's run_sql calls + their ToolMessage results are now inline messages; the dashboard
    pulls the results back out by matching tool_call ids (describe_table results are ignored)."""
    messages = [
        AIMessage(
            content="",
            tool_calls=[{"name": "describe_table", "args": {"table": "orders"}, "id": "d1"}],
        ),
        ToolMessage(content="columns: ...", tool_call_id="d1", name="describe_table"),
        AIMessage(
            content="",
            tool_calls=[{"name": "run_sql", "args": {"query": "SELECT ..."}, "id": "s1"}],
        ),
        ToolMessage(content="product|units\nAlba|73", tool_call_id="s1", name="run_sql"),
        AIMessage(content="Alba sold 73."),
    ]
    results = _sql_results_from_messages(messages)
    assert "Alba|73" in results
    assert "columns:" not in results  # describe_table results aren't dashboard context
