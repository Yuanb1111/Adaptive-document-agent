"""Large hidden views must not delay completion or download interaction."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from adaptive_document_agent.ui import result_explorer


class TrackedUI:
    def __init__(self, selected="Overview"):
        self.selected = selected
        self.session_state = {}

    def fragment(self, function):
        return function

    def tabs(self, labels, *, key, on_change):
        assert on_change == "rerun"
        return [Tab(label == self.selected) for label in labels]


class Tab:
    def __init__(self, opened):
        self.open = opened

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@pytest.mark.parametrize("selected", result_explorer.VIEW_LABELS)
def test_only_selected_tab_executes(monkeypatch, selected):
    ui, result = TrackedUI(selected), object()
    calls = {}
    for label, module in (("Overview", result_explorer.overview), ("Analysis", result_explorer.analysis),
                          ("Extracted Data", result_explorer.data), ("Sources", result_explorer.sources),
                          ("Data Quality", result_explorer.quality), ("Technical Details", result_explorer.technical)):
        calls[label] = Mock()
        monkeypatch.setattr(module, "render", calls[label])
    calls["Charts"] = Mock()
    monkeypatch.setattr(result_explorer, "_render_charts", calls["Charts"])
    result_explorer.render(ui, result, "scope")
    assert {label for label, call in calls.items() if call.called} == {selected}


def test_minimum_streamlit_uses_conditional_selector(monkeypatch):
    ui = SimpleNamespace(session_state={}, tabs=lambda labels: pytest.fail("Eager tabs must not run"),
                         segmented_control=lambda *args, **kwargs: "Overview", fragment=lambda function: function)
    overview, charts = Mock(), Mock(side_effect=AssertionError("Hidden charts ran"))
    monkeypatch.setattr(result_explorer.overview, "render", overview)
    monkeypatch.setattr(result_explorer, "_render_charts", charts)
    result_explorer.render(ui, object(), "scope")
    overview.assert_called_once()
    charts.assert_not_called()


def test_chart_pages_bound_work_and_keep_every_chart_reachable(monkeypatch):
    plans = [SimpleNamespace(id=f"chart-{i}", title=f"Measure {i}", available_chart_types=["line"],
                             chart_type="line", source_pages=[i + 1]) for i in range(12)]
    result = SimpleNamespace(observations=[], charts=plans)
    ui = Mock()
    ui.session_state = {}
    ui.expander.side_effect = lambda *args, **kwargs: nullcontext()
    ui.toggle.return_value = True
    chart = Mock(side_effect=lambda plan, *args, **kwargs: plan.id)
    rows = Mock(side_effect=lambda plan, *args: [{"Page": plan.source_pages[0]}])
    monkeypatch.setattr(result_explorer, "render_chart", chart)
    monkeypatch.setattr(result_explorer, "chart_rows", rows)
    seen = []
    for page in range(3):
        chart.reset_mock()
        ui.selectbox.side_effect = lambda label, options, **kwargs: page if label == "Chart page" else options[0]
        result_explorer._render_charts(ui, result, "scope")
        current = [call.args[0].id for call in chart.call_args_list]
        assert len(current) <= result_explorer.CHARTS_PER_PAGE
        seen.extend(current)
    assert seen == [plan.id for plan in plans]
    assert rows.call_count == 12
    assert [call.args[0][0]["Page"] for call in ui.dataframe.call_args_list] == list(range(1, 13))
    assert result.charts == plans
