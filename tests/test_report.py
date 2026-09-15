from adaptive_document_agent.agent.chart_planner import ChartPlanner
from adaptive_document_agent.agent.report_generator import ReportGenerator
from adaptive_document_agent.agent.report_planner import DynamicReportPlanner
from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import AnalysisResult, AnalysisTask, DocumentProfile, Insight, Observation, SourceEvidence
from adaptive_document_agent.ui.charts import chart_rows, render_chart


def test_dynamic_report_preserves_fact_type_and_pages() -> None:
    evidence = [SourceEvidence(page=3, text="120", extraction_method="digital_table", confidence=0.9)]
    insight = Insight(id="i", title="Revenue Growth", narrative="Revenue increased by 20%.", kind="calculated_result", evidence=evidence, confidence=0.9)
    profile = DocumentProfile(document_type="Performance report", document_purpose="Review performance")
    plan = DynamicReportPlanner().plan(profile, [insight])
    markdown = ReportGenerator().generate(profile, plan, [insight], [])
    assert "Calculated Result" in markdown
    assert "pages 3" in markdown
    assert "Trends and Changes" in markdown


def test_invalid_calculation_can_only_produce_a_reported_fact_chart() -> None:
    evidence = [SourceEvidence(page=1, text="reported", table_id="table", extraction_method="digital_table", confidence=0.9)]
    observations = [Observation(id="a", metric_original="Revenue", value=100, raw_value="100", period="2024", confidence=0.9, evidence=evidence), Observation(id="b", metric_original="Revenue", value=120, raw_value="120", period="2025", confidence=0.9, evidence=evidence)]
    index = DocumentIndex(observations)
    task = AnalysisTask(id="t", title="Revenue Change", description="d", analysis_type="absolute_change", tool_name="absolute_change", observation_query={"observation_ids": ["a", "b"]}, reason="why", expected_output="number")
    invalid = AnalysisResult(task_id="t", title="Revenue Change", result=20, evidence=[])
    charts = ChartPlanner().plan([task], [invalid], index)
    assert len(charts) == 1
    assert charts[0].analysis_task_id is None
    assert "Reported Values" in charts[0].title


def test_complete_reported_series_adds_charts_beyond_successful_calculations() -> None:
    evidence = [SourceEvidence(page=5, text="reported", table_id="table", extraction_method="digital_table", confidence=0.9)]
    observations = [
        Observation(id=f"revenue-{year}", metric_original="Revenue", value=value, raw_value=str(value), period=f"FY{year}", confidence=0.9, evidence=evidence)
        for year, value in ((2022, 100.0), (2023, 120.0), (2024, 150.0))
    ] + [
        Observation(id=f"cash-{year}", metric_original="Cash", value=value, raw_value=str(value), period=f"FY{year}", confidence=0.9, evidence=evidence)
        for year, value in ((2022, 80.0), (2023, 70.0), (2024, 60.0))
    ]
    charts = ChartPlanner().plan([], [], DocumentIndex(observations), preferred_metrics=["Revenue", "Cash"])
    assert len(charts) == 2
    assert all(chart.analysis_task_id is None for chart in charts)
    assert all(chart.chart_type == "bar" for chart in charts)
    assert all(set(chart.available_chart_types) == {"line", "bar", "table"} for chart in charts)


def test_true_cross_source_conflict_blocks_reported_series_chart() -> None:
    observations = [
        Observation(id="a", metric_original="Revenue", value=100, raw_value="100", period="FY2024", confidence=0.9),
        Observation(id="b", metric_original="Revenue", value=120, raw_value="120", period="FY2024", confidence=0.9),
        Observation(id="c", metric_original="Revenue", value=130, raw_value="130", period="FY2025", confidence=0.9),
    ]
    assert ChartPlanner().plan([], [], DocumentIndex(observations)) == []


def test_chart_planner_deduplicates_same_series_and_bounds_output() -> None:
    evidence = [SourceEvidence(page=1, text="100", extraction_method="digital_table", confidence=0.9)]
    observations = [
        Observation(id="a", metric_original="Revenue", value=100, raw_value="100", period="2024", confidence=0.9, evidence=evidence),
        Observation(id="b", metric_original="Revenue", value=120, raw_value="120", period="2025", confidence=0.9, evidence=evidence),
    ]
    index = DocumentIndex(observations)
    tasks = [
        AnalysisTask(id=f"t{i}", title=f"Revenue {i}", description="d", analysis_type=kind, tool_name=kind, observation_query={"observation_ids": ["a", "b"]}, reason="why", expected_output="number")
        for i, kind in enumerate(("absolute_change", "percentage_change", "linear_trend"))
    ]
    results = [AnalysisResult(task_id=task.id, title=task.title, result=20, evidence=evidence) for task in tasks]
    charts = ChartPlanner().plan(tasks, results, index, maximum=2)
    assert len(charts) == 1
    assert charts[0].chart_type == "bar"
    assert {"line", "bar", "area", "table"} == set(charts[0].available_chart_types)


def test_long_positive_period_series_use_a_balanced_chart_mix() -> None:
    evidence = [SourceEvidence(page=3, text="reported", extraction_method="digital_table", confidence=0.9)]
    observations = []
    tasks = []
    results = []
    for metric_index, metric in enumerate(("Revenue", "Cash", "Borrowings")):
        identifiers = []
        for year in range(2021, 2026):
            identifier = f"{metric.casefold()}-{year}"
            identifiers.append(identifier)
            observations.append(
                Observation(
                    id=identifier,
                    metric_original=metric,
                    value=float(100 + metric_index * 20 + year - 2021),
                    raw_value=str(100 + metric_index * 20 + year - 2021),
                    period=str(year),
                    confidence=0.9,
                    evidence=evidence,
                )
            )
        task = AnalysisTask(
            id=f"task-{metric_index}",
            title=f"{metric} trend",
            description="d",
            analysis_type="linear_trend",
            tool_name="linear_trend",
            required_metrics=[metric.casefold()],
            observation_query={"observation_ids": identifiers},
            reason="why",
            expected_output="trend",
        )
        tasks.append(task)
        results.append(AnalysisResult(task_id=task.id, title=task.title, result=1.0, evidence=evidence))
    charts = ChartPlanner().plan(tasks, results, DocumentIndex(observations), maximum=3)
    assert [chart.chart_type for chart in charts] == ["line", "bar", "area"]


def test_long_category_labels_default_to_horizontal_bar() -> None:
    evidence = [SourceEvidence(page=4, text="reported", extraction_method="digital_table", confidence=0.9)]
    observations = [
        Observation(
            id=f"category-{index}",
            metric_original="Revenue",
            value=float(100 - index),
            raw_value=str(100 - index),
            dimensions={"market": label},
            confidence=0.9,
            evidence=evidence,
        )
        for index, label in enumerate(("Mainland China market", "Southeast Asia market", "European market"))
    ]
    task = AnalysisTask(
        id="categories",
        title="Revenue by market",
        description="d",
        analysis_type="rank_values",
        tool_name="rank_values",
        required_metrics=["revenue"],
        required_dimensions=["market"],
        observation_query={"observation_ids": [item.id for item in observations]},
        reason="why",
        expected_output="ranking",
    )
    result = AnalysisResult(task_id=task.id, title=task.title, result=[100, 99, 98], evidence=evidence)
    plan = ChartPlanner().plan([task], [result], DocumentIndex(observations))[0]
    assert plan.chart_type == "horizontal_bar"


def test_report_includes_reported_fact_overview_and_coverage() -> None:
    evidence = [SourceEvidence(page=7, text="120", table_id="table_7", extraction_method="digital_table", confidence=0.9)]
    observation = Observation(id="revenue", metric_original="Revenue", value=120, raw_value="120", period="2025", currency="CNY", unit="currency", confidence=0.9, evidence=evidence)
    profile = DocumentProfile(document_type="Unknown data-rich document", document_purpose="Review Revenue", metrics=["Revenue"], analysis_page_ranges=[(7, 9)])
    markdown = ReportGenerator().generate(profile, DynamicReportPlanner().plan(profile, []), [], [], observations=[observation])
    assert "Evidence Coverage" in markdown
    assert "Reported Data Overview" in markdown
    assert "Analysis Coverage Check" in markdown
    assert "| Revenue | Covered |" in markdown
    assert "| Revenue | 2025 | 120 | CNY / currency | 7 | 0.90 |" in markdown


def test_report_displays_source_unit_and_scale_next_to_raw_value() -> None:
    evidence = [SourceEvidence(page=8, text="120", table_id="table_8", extraction_method="digital_table", confidence=0.9)]
    observation = Observation(
        id="scaled",
        metric_original="Revenue",
        value=120_000,
        raw_value="120",
        period="FY2025",
        currency="CNY",
        unit="currency",
        raw_unit="RMB in thousands",
        unit_scale=1_000,
        confidence=0.9,
        evidence=evidence,
    )
    profile = DocumentProfile(metrics=["Revenue"])
    markdown = ReportGenerator().generate(profile, DynamicReportPlanner().plan(profile, []), [], [], observations=[observation])
    assert "RMB in thousands / CNY / currency / source scale ×1,000" in markdown


def test_scatter_chart_pairs_by_context_and_shows_labels() -> None:
    evidence = [SourceEvidence(page=4, text="value", extraction_method="digital_table", confidence=0.9)]
    observations = []
    for year in range(2020, 2025):
        observations.extend(
            [
                Observation(id=f"right-{year}", metric_original="Right", value=float(year * 10), raw_value=str(year * 10), period=str(year), unit="days", confidence=0.9, evidence=evidence),
                Observation(id=f"left-{year}", metric_original="Left", value=float(year), raw_value=str(year), period=str(year), currency="CNY", unit="currency", confidence=0.9, evidence=evidence),
            ]
        )
    task = AnalysisTask(
        id="correlation",
        title="Left and Right relationship",
        description="Matched relationship",
        analysis_type="pearson_correlation",
        tool_name="pearson_correlation",
        required_metrics=["left", "right"],
        observation_query={"observation_ids": [item.id for item in observations]},
        reason="Five matched observations exist",
        expected_output="coefficient",
    )
    result = AnalysisResult(task_id=task.id, title=task.title, result=1.0, evidence=evidence)
    index = DocumentIndex(observations)
    plan = ChartPlanner().plan([task], [result], index)[0]
    rows = chart_rows(plan, index)
    assert [row["Label"] for row in rows] == [str(year) for year in range(2020, 2025)]
    assert rows[0]["X Value"] == 2020
    assert rows[0]["Y Value"] == 20200
    figure = render_chart(plan, index)
    assert figure.layout.xaxis.title.text.startswith("Left")
    assert list(figure.data[0].text) == [str(year) for year in range(2020, 2025)]


def test_time_chart_uses_categorical_period_axis_and_visible_values() -> None:
    evidence = [SourceEvidence(page=1, text="100", extraction_method="digital_table", confidence=0.9)]
    observations = [
        Observation(id="a", metric_original="Revenue", value=100_000_000, raw_value="100", period="2024", currency="CNY", unit="currency", confidence=0.9, evidence=evidence),
        Observation(id="b", metric_original="Revenue", value=120_000_000, raw_value="120", period="2025", currency="CNY", unit="currency", confidence=0.9, evidence=evidence),
    ]
    index = DocumentIndex(observations)
    task = AnalysisTask(id="t", title="Revenue Change", description="d", analysis_type="absolute_change", tool_name="absolute_change", required_metrics=["revenue"], observation_query={"observation_ids": ["a", "b"]}, reason="why", expected_output="number")
    result = AnalysisResult(task_id="t", title=task.title, result=20_000_000, evidence=evidence)
    plan = ChartPlanner().plan([task], [result], index)[0]
    figure = render_chart(plan, index)
    assert figure.layout.xaxis.type == "category"
    assert list(figure.data[0].text) == ["CNY 100.00M", "CNY 120.00M"]
    assert "CNY" in figure.layout.yaxis.title.text
    for style in ("bar", "area", "table"):
        assert render_chart(plan, index, chart_type=style).data


def test_contribution_chart_offers_pie_and_horizontal_bar_views() -> None:
    evidence = [SourceEvidence(page=2, text="40", extraction_method="digital_table", confidence=0.9)]
    observations = [
        Observation(id=label, metric_original="Share", value=value, raw_value=str(value), dimensions={"group": label}, unit="percent", confidence=0.9, evidence=evidence)
        for label, value in (("A", 40), ("B", 35), ("C", 25))
    ]
    task = AnalysisTask(id="share", title="Share by group", description="d", analysis_type="contribution_share", tool_name="contribution_share", required_metrics=["share"], required_dimensions=["group"], observation_query={"observation_ids": [item.id for item in observations]}, reason="why", expected_output="shares")
    result = AnalysisResult(task_id="share", title=task.title, result=[40, 35, 25], evidence=evidence)
    index = DocumentIndex(observations)
    plan = ChartPlanner().plan([task], [result], index)[0]
    assert {"pie", "bar", "horizontal_bar", "table"} == set(plan.available_chart_types)
    assert render_chart(plan, index, chart_type="pie").data
    assert render_chart(plan, index, chart_type="horizontal_bar").data
