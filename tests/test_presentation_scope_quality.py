"""Source defects remain visible without blocking an unrelated slide story."""

from adaptive_document_agent.extraction.borderless_table_extractor import BorderlessTableExtractor
from adaptive_document_agent.agent.presentation_topic_selector import series_directory
from adaptive_document_agent.models import (
    DocumentPage, ExtractedTable, PresentationPlan, PresentationTheme,
    PresentationTopic, PresentationTopicSelection, TableRow,
)
from adaptive_document_agent.services.qa_reporter import run_comprehensive_qa
from adaptive_document_agent.services.pptx_export import _usable_charts
from adaptive_document_agent.validation.presentation_data_qa import validate_presentation_data
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from tests.test_borderless_alignment_regressions import TextPage, result_for
from tests.test_pptx_export import _result


def _sparse_result():
    table = BorderlessTableExtractor().extract(TextPage("""Year ended December 31,
2021 2022 2023
Amount % Amount % Amount %
(USD in thousands)
Sales 10,000 10 20,000 20 30,000 30
Costs 5,000 5 6,000 6 7,000 7
Less: impairment (100) (200) (300)
"""), 1)[0]
    return result_for(table)


def test_unselected_ambiguous_table_is_a_warning() -> None:
    result = _sparse_result()
    result.presentation_topics = PresentationTopicSelection()
    issues = [item for item in validate_presentation_data(result)
              if item.code == "ambiguous_table_alignment"]
    assert issues and all(item.severity == "WARNING" for item in issues)


def test_ambiguous_table_used_by_theme_remains_critical() -> None:
    result = _sparse_result()
    selected = next(item for item in result.observations if item.evidence)
    result.presentation_plan = PresentationPlan(title="Evidence", themes=[PresentationTheme(
        id="sales", title="Sales", question="How did sales change?",
        rationale="Reported series", observation_ids=[selected.id],
    )])
    issues = [item for item in validate_presentation_data(result)
              if item.code == "ambiguous_table_alignment"]
    assert issues and all(item.severity == "CRITICAL" for item in issues)


def test_unselected_implausible_percentage_is_warning_but_selected_is_critical() -> None:
    result = _sparse_result()
    bad = next(item for item in result.observations if item.unit == "percent")
    bad.value = 16_465
    result.presentation_topics = PresentationTopicSelection()
    issue = next(item for item in validate_presentation_data(result)
                 if item.code == "implausible_percentage" and bad.id in item.related_ids)
    assert issue.severity == "WARNING"
    result.presentation_plan = PresentationPlan(title="Evidence", themes=[PresentationTheme(
        id="rate", title="Rate", question="How did the rate change?",
        rationale="Reported series", observation_ids=[bad.id],
    )])
    issue = next(item for item in validate_presentation_data(result)
                 if item.code == "implausible_percentage" and bad.id in item.related_ids)
    assert issue.severity == "CRITICAL"


def test_topic_directory_excludes_ambiguous_table_without_deleting_raw_fact() -> None:
    result = _result()
    bad_table = ExtractedTable(
        table_id="sparse", page=234,
        rows=[TableRow(cells=["Growth", "12%", None], page=234, alignment_status="ambiguous")],
    )
    result.document.pages = [DocumentPage(page_number=234, tables=[bad_table])]
    bad = result.observations[0].model_copy(deep=True)
    bad.id = "uncertain-revenue"
    bad.evidence[0].table_id = "sparse"
    bad.value = 999_000_000
    result.observations.append(bad)
    unsafe_chart = result.charts[0].model_copy(deep=True)
    unsafe_chart.id = "unsafe-chart"
    unsafe_chart.observation_ids = [bad.id, result.observations[1].id]
    result.charts.append(unsafe_chart)

    directory, lookup = series_directory(result)

    assert directory
    assert all(bad.id not in {item.id for item in group} for group in lookup.values())
    assert bad in result.observations  # raw extraction remains available for audit
    assert result.document.pages[0].tables[0].rows[0].alignment_status == "ambiguous"
    assert unsafe_chart.id not in {chart.id for chart in _usable_charts(result)}


def test_same_period_conflict_is_not_offered_as_one_presentation_series() -> None:
    result = _result()
    conflict = result.observations[0].model_copy(deep=True)
    conflict.id = "conflicting-revenue"
    conflict.value += 10_000
    result.observations.append(conflict)

    _, lookup = series_directory(result)

    assert not any(conflict.id in {item.id for item in group} for group in lookup.values())


def test_selected_questions_without_valid_slide_plan_block_export_explicitly() -> None:
    result = _result()
    series_id = series_directory(result)[0][0]["id"]
    result.presentation_topics = PresentationTopicSelection(topics=[PresentationTopic(
        id="growth", title="Revenue movement", question="How did revenue move?",
        rationale="The source reports comparable values.", series_ids=[series_id],
    )])

    qa = run_comprehensive_qa(result)

    assert any(item.code == "presentation_plan_missing" for item in qa.critical_errors)


def test_interim_period_label_is_not_misread_as_unsupported_duration() -> None:
    assert PresentationPlanValidator._numbers("from 6M2023 to 6M2024") == {"2023", "2024"}


def test_qa_revalidates_repaired_plan_before_reporting_export_ready() -> None:
    result = _result()
    result.presentation_plan = PresentationPlan(
        title="Revenue review", planning_origin="topic_recovery",
        slides=[],
    )

    qa = run_comprehensive_qa(result, auto_repair=True)

    assert any(item.code == "presentation_plan_invalid_after_repair" for item in qa.critical_errors)
