"""Chart captions compute only compatible observed changes."""

from adaptive_document_agent.services.presentation_chart_annotation import chart_change_annotation
from test_presentation_key_figures import _result
from test_source_row_composition import source_matrix
from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.services.composition_candidates import presentation_compositions


def test_largest_adjacent_change_uses_exact_reported_periods():
    result = _result()
    chart = result.charts[0]
    index = {item.id: item for item in result.observations}
    assert chart_change_annotation(chart, index) == "FY2022 to FY2023: +10.0 units"


def test_explicit_slide_periods_use_endpoint_change_and_hide_unknown_unit():
    result = _result()
    chart = result.charts[0]
    first = result.observations[0]
    middle = result.observations[1]
    last = middle.model_copy(deep=True, update={"id": "measure-0-2024", "period": "FY2024",
                                                "value": 18.0, "raw_value": "18"})
    for item in (first, middle, last):
        item.unit, item.raw_unit = "unknown", "unknown"
    chart.observation_ids.append(last.id)
    index = {item.id: item for item in (first, middle, last)}
    assert chart_change_annotation(chart, index) == "FY2022 to FY2023: +10.0"
    assert chart_change_annotation(chart, index, scope_text="Growth from FY2022 to FY2024") == (
        "FY2022 to FY2024: +8.00")


def test_mixed_period_and_conflicting_values_have_no_annotation():
    result = _result()
    chart = result.charts[0]
    result.observations[1].period = "6M2023"
    result.observations[1].period_basis = "6M"
    result.observations[1].period_type = "interim_flow"
    assert chart_change_annotation(chart, {item.id: item for item in result.observations}) == ""


def test_complete_mix_labels_largest_reported_share_change():
    observations = source_matrix()
    for item in observations:
        if item.evidence[0].row_label == "Hardware" and item.period == "FY2024":
            item.value = 50
            item.raw_value = "50"
        if item.evidence[0].row_label == "Other" and item.period == "FY2024":
            item.value = 0
            item.raw_value = "0"
    chart = next(chart for chart in presentation_compositions(DocumentIndex(observations))
                 if chart.chart_type == "stacked_percent")
    annotation = chart_change_annotation(chart, {item.id: item for item in observations})
    assert "Hardware share" in annotation
    assert "FY2023 to FY2024" in annotation
    assert "+10.0 pp" in annotation
