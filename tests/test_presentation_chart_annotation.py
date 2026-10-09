"""Chart captions compute only compatible observed changes."""

from adaptive_document_agent.services.presentation_chart_annotation import chart_change_annotation
from test_presentation_key_figures import _result
from test_source_row_composition import source_matrix
from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.services.composition_candidates import presentation_compositions


def test_latest_adjacent_change_uses_exact_reported_periods():
    result = _result()
    chart = result.charts[0]
    index = {item.id: item for item in result.observations}
    assert chart_change_annotation(chart, index) == "FY2022 to FY2023: +10 units"


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
    assert chart_change_annotation(chart, index) == "FY2023 to FY2024: -2.00"
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


def test_price_change_preserves_source_denominator():
    from adaptive_document_agent.models import ChartPlan, Observation, SourceEvidence

    observations = [Observation(id=f'p{i}', metric_original='Average selling price',
        period=f'FY{2022+i}', value=value, raw_value=str(value / 1000),
        unit='currency', currency='RMB', raw_unit='RMB in thousands/unit',
        unit_scale=1000, confidence=1, validation_status='valid',
        evidence=[SourceEvidence(page=1, text=str(value / 1000), extraction_method='digital_table', confidence=1)])
        for i, value in enumerate((62000, 54000))]
    chart = ChartPlan(id='price', title='Average selling price', chart_type='line',
                      question='How did the price change?',
                      observation_ids=[item.id for item in observations])
    before = [item.model_dump() for item in observations]
    assert chart_change_annotation(chart, {item.id: item for item in observations}).endswith(
        '-8.00 RMB thousands/unit')
    assert [item.model_dump() for item in observations] == before


def test_iso_endpoint_scope_matches_date_labels_with_audit_marker():
    result = _result()
    first = result.observations[0]
    points = [first.model_copy(deep=True, update={
        'id': f'date-{i}', 'period': day, 'as_of_date': day,
        'period_type': 'balance_sheet_date', 'period_basis': 'date',
        'value': value, 'raw_value': str(value),
        'audited_status': 'unaudited' if i == 2 else 'unknown'})
        for i, (day, value) in enumerate(zip(
            ('2022-12-31', '2023-12-31', '2024-10-31'), (100, 20, 30)))]
    chart = result.charts[0].model_copy(update={'observation_ids': [o.id for o in points]})
    index = {o.id: o for o in points}
    assert chart_change_annotation(chart, index).endswith('+10 units')
    assert chart_change_annotation(chart, index,
        scope_text='From 2022-12-31 to 2024-10-31').endswith('-70 units')
