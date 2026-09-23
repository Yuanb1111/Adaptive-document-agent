"""Source defects remain visible without blocking an unrelated slide story."""

from adaptive_document_agent.extraction.borderless_table_extractor import BorderlessTableExtractor
from adaptive_document_agent.models import PresentationPlan, PresentationTheme, PresentationTopicSelection
from adaptive_document_agent.validation.presentation_data_qa import validate_presentation_data
from tests.test_borderless_alignment_regressions import TextPage, result_for


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
