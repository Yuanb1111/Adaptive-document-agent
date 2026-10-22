"""Readable chart space and complete evidence, without sparse continuations."""
import pytest

from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.services.composition_pagination import unplotted_table_ids
from adaptive_document_agent.services.data_index_layout import fit_columns, balanced_pages
from adaptive_document_agent.services.slide_compositor import compose_geometry
from adaptive_document_agent.services.text_capacity import wrap_copy
from tests.test_p0_composition import observation


def test_charted_group_deduplication_never_removes_a_partial_period_series():
    rows = [observation(f'{metric}{year}', metric, year, f'FY{year}')
            for metric in ('First measure', 'Second measure') for year in (2022, 2023)]
    ids = [o.id for o in rows]
    kept = unplotted_table_ids(ids, {ids[0], *ids[2:]}, DocumentIndex(rows))
    assert kept == ids[:2]  # One plotted endpoint cannot erase half a table.
    assert unplotted_table_ids(ids, set(ids), DocumentIndex(rows)) == []
    assert unplotted_table_ids(ids, set(), DocumentIndex(rows)) == ids


def test_short_commentary_gives_space_back_to_native_charts():
    short = compose_geometry(12.6, 7.09, 1.5, 2, layout='two_up', has_support=False,
                             has_commentary=True, commentary_text='Reported measurements.')
    long = compose_geometry(12.6, 7.09, 1.5, 2, layout='two_up', has_support=False,
                            has_commentary=True, commentary_text='A complete source qualification. ' * 12)
    assert short.charts[0].h > long.charts[0].h
    assert short.commentary.h < 1.22
    assert short.charts[0].y + short.charts[0].h < short.commentary.y


def test_measured_index_columns_fit_long_topics_without_a_single_row_continuation():
    values = [[f'Measure {i}: reported production, operating capacity and activity across the disclosed periods',
               'units', 'FY2021; FY2022; FY2023', '12, 17, 39'] for i in range(6)]
    width = 11.5
    old_widths = [width * f for f in (.30, .13, .39, .18)]
    old = [(row, max(.44, max(len(wrap_copy(v, w - .16, 12)) * .22 + .12
                             for v, w in zip(row, old_widths)))) for row in values]
    widths, rows = fit_columns(values, width)
    assert sum(widths) == pytest.approx(width)
    assert sum(h for _, h in rows) < sum(h for _, h in old)
    assert len(balanced_pages(rows, 4.4)) == 1
    assert len(balanced_pages(old, 4.4)) == 2
    assert [row for row, _ in rows] == values


def test_unavoidable_index_pages_are_balanced_without_reordering():
    rows = [([str(i)] * 4, 1.0) for i in range(7)]
    pages = balanced_pages(rows, 5.4)
    assert sorted(map(len, pages)) == [3, 4]
    assert [row for page in pages for row in page] == rows


def test_oversized_index_entry_is_not_truncated():
    with pytest.raises(ValueError, match='exceeds readable page capacity'):
        balanced_pages([(['A complete source scope'] * 4, 6.0)], 4.4)


def test_continuations_keep_original_comparison_interval_without_repeating_the_question():
    from adaptive_document_agent.models import ChartPlan, PresentationSlide
    from adaptive_document_agent.services.slide_compositor import _paginate_chart_slide
    from tests.test_p0_composition import result_for
    from tests.test_presentation_brief import blank_deck
    records = [observation(f'{metric}-{year}', metric, value, f'FY{year}')
               for metric in ('Output', 'Capacity')
               for year, value in ((2021, 20), (2022, 30), (2023, 50))]
    charts = [ChartPlan(id=metric, title=metric, question='Reported values', chart_type='bar',
        observation_ids=[o.id for o in records if o.metric_original == metric], source_pages=[3])
        for metric in ('Output', 'Capacity')]
    plan = PresentationSlide(id='comparison', slide_type='analysis', title='Reported output and capacity',
        section_title='Reported output and capacity', message='Reported values from FY2021 to FY2023.',
        chart_ids=[c.id for c in charts], source_pages=[3])
    result = result_for(records, charts, plan)
    # The source interval is part of the original question even when the
    # continuation subtitle is empty. It must remain the annotation interval.
    plan.section_title = 'Reported output and capacity, FY2021-FY2023'
    deck = blank_deck()
    pages = _paginate_chart_slide(deck, plan, ([charts[0]], [charts[1]]), result, DocumentIndex(records))
    annotations = [s.text for page in pages for s in page.shapes if s.name.startswith('annotation:')]
    assert all('FY2021 to FY2023' in text for text in annotations)
    assert any('(continued)' in s.text for s in pages[-1].shapes if s.has_text_frame)
    assert not any('Reported output and capacity' in s.text for s in pages[-1].shapes
                   if s.has_text_frame and s.name.startswith('composed:text:') and not s.text.startswith('Source:'))
