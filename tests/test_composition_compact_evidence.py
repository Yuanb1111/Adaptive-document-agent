"""Complete topic evidence fits before page budgets remove useful topics."""

import json

import pytest

from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import ChartPlan, PresentationSlide, PresentationVisualBlock
from adaptive_document_agent.services.slide_compositor import render_composed_slide, validate_composed_geometry
from tests.test_p0_composition import observation, result_for
from tests.test_presentation_brief import blank_deck


def _topic_fixture():
    records, charts = [], []
    names = ('Reported measurement', 'Adjusted measurement (alternative basis)',
             'First disclosed adjustment', 'Second disclosed adjustment')
    for metric, name in enumerate(names):
        values = [observation(f'm{metric}-{year}', name, 20 + metric * 10 + year - 2020,
                              f'6M{year}', unit='count')
                  for year in ([2024] if metric == 3 else [2023, 2024])]
        for item in values:
            item.period_basis = '6M'
            item.period_type = 'interim_flow'
            item.audited_status = 'unaudited' if item.period == '6M2023' else 'unknown'
        records.extend(values)
        if metric < 3:
            charts.append(ChartPlan(id=f'c{metric}', title=name + ' — Reported Values', chart_type='line',
                question='What measurements were reported?', observation_ids=[item.id for item in values], source_pages=[3]))
    plan = PresentationSlide(id='measurements', slide_type='analysis', theme_id='measurements',
        title='Interim reported measurement versus adjusted measurement and disclosed adjustment items',
        section_title='Measurement comparison',
        message='What were the reported and adjusted measurements and the disclosed adjustment items in 6M2024?',
        chart_ids=[chart.id for chart in charts], observation_ids=[item.id for item in records],
        layout='three_up', source_pages=[3],
        visual_blocks=[PresentationVisualBlock(role='table', observation_ids=[item.id for item in records])])
    return result_for(records, charts, plan)


def test_charted_series_stay_in_charts_and_unplotted_support_has_no_orphan_rows():
    result = _topic_fixture()
    before = result.model_dump_json()
    deck = blank_deck()
    slides = render_composed_slide(deck, result.presentation_plan.slides[3], result.charts,
                                  result, DocumentIndex(result.observations))
    validate_composed_geometry(deck)
    assert len(slides) == len(deck.slides) == 1
    assert [sum(shape.has_chart for shape in slide.shapes) for slide in slides] == [3]
    tables = [shape.table for slide in slides for shape in slide.shapes if shape.has_table]
    assert len(tables) == 1
    table = tables[0]
    assert [table.cell(0, c).text for c in range(3)] == ['Metric', 'Period', 'Value']
    assert len(table.rows) == 2
    missing_row = next(row for row in table.rows if row.cells[0].text == 'Second disclosed adjustment')
    assert missing_row.cells[1].text == '6M2024'
    assert '54' in missing_row.cells[2].text
    assert [list(s.chart.series[0].values) for s in slides[0].shapes if s.has_chart] == [
        [23, 24], [33, 34], [43, 44]]
    notes = [json.loads(slide.notes_slide.notes_text_frame.text) for slide in slides]
    assert {item['id'] for note in notes for item in note['observations']} == {item.id for item in result.observations}
    assert result.model_dump_json() == before


@pytest.mark.parametrize('period', ['FY2024', '3M2024', 'Unspecified'])
def test_sparse_matrix_rejects_unknown_or_incompatible_period_basis(period):
    from adaptive_document_agent.services.composition_pagination import sparse_period_columns
    groups = [[observation('a23', 'First measure', 2, '6M2023'),
               observation('a24', 'First measure', 3, '6M2024')],
              [observation('b24', 'Second measure', 4, period)]]
    assert sparse_period_columns(groups) == ()


def test_sparse_matrix_keeps_conflicting_same_period_records_as_rows():
    from adaptive_document_agent.services.composition_pagination import sparse_period_columns
    groups = [[observation('a23', 'First measure', 2, '6M2023'),
               observation('a24', 'First measure', 3, '6M2024')],
              [observation('b24', 'Second measure', 4, '6M2024'),
               observation('b24-conflict', 'Second measure', 5, '6M2024')]]
    assert sparse_period_columns(groups) == ()


@pytest.mark.parametrize('date_source', ['iso', 'as_of_date'])
def test_sparse_point_dates_keep_source_precision(date_source):
    from adaptive_document_agent.services.composition_pagination import sparse_period_columns
    groups = [[observation(f'a{year}', 'First balance', year, f'{year}-06-30')
               for year in (2022, 2023, 2024)],
              [observation(f'b{year}', 'Second balance', year, f'{year}-06-30')
               for year in (2023, 2024)]]
    if date_source == 'as_of_date':
        for group in groups:
            for item in group:
                item.as_of_date = item.period
                item.period = 'Interim balance'
                item.period_type = 'balance_sheet_date'
            group.reverse()
    assert sparse_period_columns(groups) == ('30 Jun 2022', '30 Jun 2023', '30 Jun 2024')


def test_different_audit_qualifiers_do_not_duplicate_one_date_column():
    from adaptive_document_agent.services.composition_pagination import sparse_period_columns
    groups = [[observation(f'a{year}', 'First balance', year, f'{year}-06-30')
               for year in (2022, 2023, 2024)],
              [observation(f'b{year}', 'Second balance', year, f'{year}-06-30')
               for year in (2023, 2024)]]
    groups[1][-1].audited_status = 'unaudited'
    assert sparse_period_columns(groups) == ()


@pytest.mark.parametrize('bounds', [
    ('2024-04-01', '2024-09-30'),
    ('2024-01-01', '2024-09-30'),
    ('2024-04-01', '2024-06-30'),
    (None, None),
    ('2024-01-01', None),
    (None, '2024-06-30'),
])
def test_sparse_duration_columns_reject_conflicting_or_missing_explicit_intervals(bounds):
    from adaptive_document_agent.services.composition_pagination import sparse_period_columns
    groups = [[observation('a23', 'First measure', 2, '6M2023'),
               observation('a24', 'First measure', 3, '6M2024')],
              [observation('b24', 'Second measure', 4, '6M2024')]]
    for year, item in zip((2023, 2024), groups[0]):
        item.period_start, item.period_end = f'{year}-01-01', f'{year}-06-30'
    groups[1][0].period_start, groups[1][0].period_end = bounds
    assert sparse_period_columns(groups) == ()


def test_sparse_duration_columns_accept_identical_explicit_intervals():
    from adaptive_document_agent.services.composition_pagination import sparse_period_columns
    groups = [[observation('a23', 'First measure', 2, '6M2023'),
               observation('a24', 'First measure', 3, '6M2024')],
              [observation('b24', 'Second measure', 4, '6M2024')]]
    for group in groups:
        for item in group:
            year = item.period[-4:]
            item.period_start, item.period_end = f'{year}-01-01', f'{year}-06-30'
    assert sparse_period_columns(groups) == ('6M2023', '6M2024')


def test_full_matrix_also_rejects_same_labels_with_different_explicit_intervals():
    records = [observation(f'{metric}{year}', metric, year, f'6M{year}')
               for metric in ('First measure', 'Second measure') for year in (2023, 2024)]
    for item in records:
        year = item.period[-4:]
        item.period_start, item.period_end = f'{year}-01-01', f'{year}-06-30'
    records[-1].period_start, records[-1].period_end = '2024-04-01', '2024-09-30'
    plan = PresentationSlide(id='source', slide_type='analysis', title='Reported source records',
        layout='data_overview', observation_ids=[item.id for item in records],
        visual_blocks=[PresentationVisualBlock(role='table', observation_ids=[item.id for item in records])])
    result = result_for(records, [], plan)
    deck = blank_deck()
    slides = render_composed_slide(deck, plan, [], result, DocumentIndex(records))
    tables = [shape.table for slide in slides for shape in slide.shapes if shape.has_table]
    assert tables
    assert all([table.cell(0, c).text for c in range(len(table.columns))] == ['Metric', 'Period', 'Value']
               for table in tables)


def test_table_deduplication_preserves_equal_values_for_different_explicit_intervals():
    records = [observation('first', 'Measured output', 10, '6M2024'),
               observation('different-range', 'Measured output', 10, '6M2024')]
    records[0].period_start, records[0].period_end = '2024-01-01', '2024-06-30'
    records[1].period_start, records[1].period_end = '2024-04-01', '2024-09-30'
    plan = PresentationSlide(id='source', slide_type='analysis', title='Reported source records',
        layout='data_overview', observation_ids=[item.id for item in records],
        visual_blocks=[PresentationVisualBlock(role='table', observation_ids=[item.id for item in records])])
    result = result_for(records, [], plan)
    deck = blank_deck()
    slides = render_composed_slide(deck, plan, [], result, DocumentIndex(records))
    tables = [shape.table for slide in slides for shape in slide.shapes if shape.has_table]
    assert sum(len(table.rows) - 1 for table in tables) == 2
